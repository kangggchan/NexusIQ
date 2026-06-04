"""
Workforce catalog — Neo4j-backed workforce evidence for people, profile, team, and project questions.

Data Source:
  - Neo4j: Employee, Service, and Team nodes
  - No local data folder access
"""
from __future__ import annotations

import re
from typing import Any

from retrieval.graph.neo4j_client import get_session


class WorkforceCatalog:
    """Neo4j-backed workforce evidence for people, profile, team, and project questions."""

    def __init__(self) -> None:
        self._loaded = False
        self._employees: list[dict[str, Any]] = []
        self._employees_by_name: dict[str, dict[str, Any]] = {}
        self._services_by_name: dict[str, dict[str, Any]] = {}
        self._teams_by_name: dict[str, dict[str, Any]] = {}
        self._project_aliases: dict[str, str] = {}

    async def load(self) -> None:
        if self._loaded:
            return

        try:
            async with get_session() as session:
                # Load employees from Neo4j
                emp_result = await session.run("MATCH (e:Employee) RETURN e")
                self._employees = [dict(record["e"]) async for record in emp_result]
                
                self._employees_by_name = {
                    _norm(emp.get("name", "")): emp
                    for emp in self._employees
                    if emp.get("name")
                }
                
                # Extract teams from employees
                teams_set = {emp.get("team", "") for emp in self._employees if emp.get("team")}
                self._teams_by_name = {
                    _norm(team): {"name": team}
                    for team in teams_set
                    if team
                }

                # Load services from Neo4j
                svc_result = await session.run("MATCH (s:Service) RETURN s")
                services = [dict(record["s"]) async for record in svc_result]
                
                self._services_by_name = {
                    _norm(s.get("name", "")): s
                    for s in services
                    if s.get("name")
                }

                # Build project aliases
                project_names = {
                    s.get("project", "")
                    for s in services
                    if s.get("project")
                }
                for employee in self._employees:
                    project_names.update(p for p in employee.get("projects", []) if p)

                for project in project_names:
                    norm = _norm(project)
                    if not norm:
                        continue
                    self._project_aliases[norm] = project
                    tokens = set(re.findall(r"[a-z0-9]+", norm))
                    for family in ("adas", "lidar"):
                        if family in tokens:
                            self._project_aliases[f"{family} project"] = project

            self._loaded = True
        except Exception as exc:
            # Log but don't fail - workforce catalog is optional
            import logging
            logging.getLogger(__name__).warning("WorkforceCatalog could not load from Neo4j: %s", exc)

    async def build_people_documents(
        self,
        *,
        query: str,
        answer_goal: str,
        query_entities: list[str],
    ) -> list[dict[str, Any]]:
        await self.load()

        employees = self._resolve_employees(query, answer_goal, query_entities)
        services = self._resolve_services(query, answer_goal, query_entities)
        projects = self._resolve_projects(query, answer_goal, query_entities, services)
        teams = self._resolve_teams(query, answer_goal, query_entities, services)

        docs: list[dict[str, Any]] = []

        for employee in employees[:4]:
            doc = self._employee_profile_doc(employee)
            if doc:
                docs.append(doc)

        for service in services[:2]:
            doc = self._service_staffing_doc(service)
            if doc:
                docs.append(doc)

        for project in projects[:2]:
            doc = self._project_staffing_doc(project)
            if doc:
                docs.append(doc)

        for team in teams[:2]:
            doc = self._team_staffing_doc(team)
            if doc:
                docs.append(doc)

        if (
            not docs
            and not employees
            and not services
            and not projects
            and not teams
            and self._is_company_wide_query(query, answer_goal, query_entities)
        ):
            docs.append(self._company_staffing_doc())

        unique_docs: list[dict[str, Any]] = []
        seen_ids: set[str] = set()
        for doc in docs:
            doc_id = str(doc.get("id", ""))
            if not doc_id or doc_id in seen_ids:
                continue
            seen_ids.add(doc_id)
            unique_docs.append(doc)
        return unique_docs

    def resolve_employee_names(self, *texts: str) -> list[str]:
        combined = _norm(" ".join(text for text in texts if text))
        employees = [
            employee.get("name", "")
            for key, employee in self._employees_by_name.items()
            if key and key in combined
        ]
        return _dedupe(employees)

    def _resolve_employees(self, query: str, answer_goal: str, query_entities: list[str]) -> list[str]:
        return self.resolve_employee_names(query, answer_goal, *query_entities)

    def _is_company_wide_query(self, query: str, answer_goal: str, query_entities: list[str]) -> bool:
        combined = _norm(" ".join([query, answer_goal, *query_entities]))
        company_markers = [
            "company",
            "workforce",
            "all employees",
            "total employees",
            "employees do we have",
            "employees are there",
            "people do we have",
        ]
        return any(marker in combined for marker in company_markers)

    def _resolve_services(self, query: str, answer_goal: str, query_entities: list[str]) -> list[str]:
        combined = _norm(f"{query} {answer_goal}")
        services = [
            svc.get("name", "")
            for key, svc in self._services_by_name.items()
            if key and key in combined
        ]
        if services:
            return _dedupe(services)

        fallback = [
            entity for entity in query_entities
            if _norm(entity) in self._services_by_name
        ]
        return _dedupe(fallback[:1])

    def _resolve_projects(
        self,
        query: str,
        answer_goal: str,
        query_entities: list[str],
        services: list[str],
    ) -> list[str]:
        combined = _norm(" ".join([query, answer_goal, *query_entities]))
        projects = [
            project
            for alias, project in self._project_aliases.items()
            if alias and alias in combined
        ]
        if projects:
            return _dedupe(projects)

        if "project" in combined:
            inferred = [
                self._services_by_name[_norm(service)].get("project", "")
                for service in services
                if _norm(service) in self._services_by_name
            ]
            return _dedupe([project for project in inferred if project])

        return []

    def _resolve_teams(self, query: str, answer_goal: str, query_entities: list[str], services: list[str]) -> list[str]:
        combined = _norm(" ".join([query, answer_goal, *query_entities]))
        teams = [
            team.get("name", "")
            for key, team in self._teams_by_name.items()
            if key and key in combined
        ]
        if teams:
            return _dedupe(teams)

        inferred = [
            self._services_by_name[_norm(service)].get("team", "")
            for service in services
            if _norm(service) in self._services_by_name
        ]
        return _dedupe([team for team in inferred if team])

    def _service_staffing_doc(self, service_name: str) -> dict[str, Any] | None:
        service = self._services_by_name.get(_norm(service_name))
        if not service:
            return None

        team_name = service.get("team", "")
        members = [
            employee for employee in self._employees
            if employee.get("team", "") == team_name
        ]
        owners = [
            employee for employee in self._employees
            if service_name in employee.get("owned_services", [])
        ]
        if not members and not owners:
            return None

        member_names = ", ".join(employee.get("name", "") for employee in members)
        owner_names = ", ".join(employee.get("name", "") for employee in owners) or "NONE"
        return {
            "id": f"workforce::service::{service_name}",
            "source": "workforce",
            "collection": "workforce_catalog",
            "rrf_score": 1.0,
            "content": (
                f"[SERVICE STAFFING] {service_name} is assigned to team {team_name}. "
                f"Team members ({len(members)}): {member_names}. "
                f"Named service owner(s): {owner_names}."
            ),
            "metadata": {
                "scope": "service",
                "service": service_name,
                "team": team_name,
                "member_count": len(members),
                "members": [employee.get("name", "") for employee in members],
                "owners": [employee.get("name", "") for employee in owners],
            },
        }

    def _employee_profile_doc(self, employee_name: str) -> dict[str, Any] | None:
        employee = self._employees_by_name.get(_norm(employee_name))
        if not employee:
            return None

        projects = employee.get("projects", [])
        owned_services = employee.get("owned_services", [])
        manager = employee.get("manager") or "NONE"
        return {
            "id": f"workforce::employee::{employee.get('employee_id', _slug(employee_name))}",
            "source": "workforce",
            "collection": "workforce_catalog",
            "rrf_score": 1.0,
            "content": (
                f"[EMPLOYEE PROFILE] {employee.get('name', employee_name)} is a {employee.get('role', '')} "
                f"on {employee.get('team', '')}. Projects: {', '.join(projects) or 'NONE'}. "
                f"Owned services: {', '.join(owned_services) or 'NONE'}. "
                f"Manager: {manager}."
            ),
            "metadata": {
                "scope": "employee",
                "employee_id": employee.get("employee_id", ""),
                "name": employee.get("name", employee_name),
                "role": employee.get("role", ""),
                "team": employee.get("team", ""),
                "projects": projects,
                "owned_services": owned_services,
                "manager": manager,
            },
        }

    def _project_staffing_doc(self, project_name: str) -> dict[str, Any] | None:
        members = [
            employee for employee in self._employees
            if project_name in employee.get("projects", [])
        ]
        if not members:
            return None

        member_names = ", ".join(employee.get("name", "") for employee in members)
        return {
            "id": f"workforce::project::{_slug(project_name)}",
            "source": "workforce",
            "collection": "workforce_catalog",
            "rrf_score": 1.0,
            "content": (
                f"[PROJECT STAFFING] {project_name} has {len(members)} employees: {member_names}."
            ),
            "metadata": {
                "scope": "project",
                "project": project_name,
                "member_count": len(members),
                "members": [employee.get("name", "") for employee in members],
            },
        }

    def _team_staffing_doc(self, team_name: str) -> dict[str, Any] | None:
        members = [
            employee for employee in self._employees
            if employee.get("team", "") == team_name
        ]
        if not members:
            return None

        member_names = ", ".join(employee.get("name", "") for employee in members)
        return {
            "id": f"workforce::team::{_slug(team_name)}",
            "source": "workforce",
            "collection": "workforce_catalog",
            "rrf_score": 1.0,
            "content": (
                f"[TEAM STAFFING] {team_name} has {len(members)} employees: {member_names}."
            ),
            "metadata": {
                "scope": "team",
                "team": team_name,
                "member_count": len(members),
                "members": [employee.get("name", "") for employee in members],
            },
        }

    def _company_staffing_doc(self) -> dict[str, Any]:
        member_names = ", ".join(employee.get("name", "") for employee in self._employees)
        return {
            "id": "workforce::company::all_employees",
            "source": "workforce",
            "collection": "workforce_catalog",
            "rrf_score": 1.0,
            "content": (
                f"[WORKFORCE SUMMARY] NovaDrive AI has {len(self._employees)} employees: {member_names}."
            ),
            "metadata": {
                "scope": "company",
                "member_count": len(self._employees),
                "members": [employee.get("name", "") for employee in self._employees],
            },
        }


_catalog: WorkforceCatalog | None = None


async def get_workforce_catalog() -> WorkforceCatalog:
    global _catalog
    if _catalog is None:
        _catalog = WorkforceCatalog()
        await _catalog.load()
    return _catalog


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip().lower())


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", _norm(text)).strip("-")


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        key = _norm(item)
        if not key or key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result
