import type { Metadata, Viewport } from "next";
import { Fraunces, Source_Sans_3 } from "next/font/google";
import "./globals.css";

const display = Fraunces({
  variable: "--font-fraunces",
  subsets: ["latin"],
});

const sans = Source_Sans_3({
  variable: "--font-source",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "Mediator — private rooms for family disputes",
  description:
    "A culturally aware shuttle-diplomacy mediator for Indian personal and family conflicts.",
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  themeColor: "#f3ead9",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en" className={`${display.variable} ${sans.variable} h-full`}>
      <body className="min-h-full font-sans antialiased">{children}</body>
    </html>
  );
}
