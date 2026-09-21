import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "2J Group Beauty Store",
  description: "Browse 2J beauty supplies by item number. Private staff ordering and a public product catalog.",
  other: {
    "codex-preview": "development",
  },
  icons: {
    icon: "/favicon.svg",
    shortcut: "/favicon.svg",
  },
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body className="antialiased">{children}</body>
    </html>
  );
}
