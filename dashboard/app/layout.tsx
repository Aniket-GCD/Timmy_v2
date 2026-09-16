import type { Metadata } from "next";
import { Marcellus, PT_Serif } from "next/font/google";
import "./globals.css";

const marcellus = Marcellus({
  weight: "400",
  subsets: ["latin"],
  variable: "--font-marcellus",
});

const ptSerif = PT_Serif({
  weight: ["400", "700"],
  subsets: ["latin"],
  variable: "--font-pt-serif",
});

export const metadata: Metadata = {
  title: "Timmy Dashboard",
  description: "Firm hours dashboard for Timmy time entries across GCD and MH.",
  icons: {
    icon: [{ url: "/timmy-icon-white.svg", type: "image/svg+xml" }],
  },
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body className={`${marcellus.variable} ${ptSerif.variable}`} suppressHydrationWarning>
        {children}
      </body>
    </html>
  );
}
