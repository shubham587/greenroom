import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Greenroom",
  description: "Practise the interview before you have it.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
