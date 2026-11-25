import type { Metadata } from "next";
import "./globals.css";
const origin = "https://gaffers-gambit.tartan-fantasy.workers.dev";
export const metadata: Metadata = {
  metadataBase: new URL(origin),
  title: "Gaffer’s Gambit — The daily football rarity game",
  description:
    "Think you know ball? Seven questions, 25 seconds each. Rarer answers score more. Play the free daily football challenge and take on your mates.",
  alternates: { canonical: "/" },
  openGraph: {
    title: "Gaffer’s Gambit",
    description:
      "Seven questions. Rarer answers score more. Can you beat your mates?",
    url: origin,
    siteName: "Gaffer’s Gambit",
    type: "website",
    images: [
      {
        url: "/social-launch.png",
        width: 1200,
        height: 630,
        type: "image/png",
        alt: "Gaffer’s Gambit. Think you know ball? Seven questions. Rarer answers score more.",
      },
    ],
  },
  twitter: {
    card: "summary_large_image",
    title: "Gaffer’s Gambit",
    description:
      "Seven questions. Rarer answers score more. Can you beat your mates?",
    images: [
      {
        url: "/social-launch.png",
        alt: "Gaffer’s Gambit. Think you know ball? Seven questions. Rarer answers score more.",
      },
    ],
  },
  icons: { icon: "/favicon.svg" },
};
export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
