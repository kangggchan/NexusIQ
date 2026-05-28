import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import Image from "next/image";
import "./globals.css";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "NexusIQ — Enterprise Operational Intelligence",
  description: "AI-powered enterprise investigation platform for operational incident analysis. Explore service dependencies, incident timelines, and multi-agent AI reasoning.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body
        className={`${geistSans.variable} ${geistMono.variable} antialiased`}
      >
        {children}
        <div className="fixed bottom-4 right-4 z-50">
          <Image
            src="/logo.png"
            alt="Logo"
            width={48}
            height={48}
          />
        </div>
      </body>
    </html>
  );
}
