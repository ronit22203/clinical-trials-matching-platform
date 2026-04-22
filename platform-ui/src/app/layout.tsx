import type { Metadata } from "next";
import { Inter, Manrope } from "next/font/google";
import "./globals.css";
import { ThemeProvider } from "@/components/layout/ThemeProvider";

const inter = Inter({
  variable: "--font-inter",
  subsets: ["latin"],
  display: "swap",
});

const manrope = Manrope({
  variable: "--font-manrope",
  subsets: ["latin"],
  display: "swap",
});

export const metadata: Metadata = {
  title: "Clinical Trial Matching | Medical Research AI",
  description: "Decision system for clinicians — evidence + traceability + speed",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" className={`${inter.variable} ${manrope.variable} h-full`} suppressHydrationWarning>
      <body className="h-full bg-surface text-on-surface antialiased">
        <ThemeProvider>{children}</ThemeProvider>
      </body>
    </html>
  );
}
