import { NextResponse } from 'next/server'
import path from 'node:path'
import fs from 'node:fs/promises'

const DATA_DIR = path.join(process.cwd(), 'data', 'nexusiq_dataset')

export async function GET() {
  try {
    const raw = await fs.readFile(path.join(DATA_DIR, 'incidents.json'), 'utf-8')
    const data = JSON.parse(raw)
    return NextResponse.json(data.incidents ?? [])
  } catch (err) {
    console.error('[nexusiq/incidents]', err)
    return NextResponse.json({ error: 'Failed to load incidents' }, { status: 500 })
  }
}
