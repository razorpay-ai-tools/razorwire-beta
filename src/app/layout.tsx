import type { Metadata, Viewport } from 'next';
import { Inter, JetBrains_Mono } from 'next/font/google';
import './globals.css';

// Token names in globals.css point at these variables, so the font pair is loaded
// here rather than referenced by family name and hoped for.
const inter = Inter({ variable: '--font-inter', subsets: ['latin'], display: 'swap' });
const jetbrainsMono = JetBrains_Mono({
  variable: '--font-jetbrains-mono',
  subsets: ['latin'],
  display: 'swap',
});

export const metadata: Metadata = {
  title: 'Razorwire',
  description: 'Every tech spec ships with a 60-second explainer.',
};

/**
 * The feed is full-bleed `h-dvh` video, so the viewport must not be zoomable-scrolled
 * out from under the snap container, and dark is the only theme.
 */
export const viewport: Viewport = {
  themeColor: '#090a0f',
  colorScheme: 'dark',
  width: 'device-width',
  initialScale: 1,
};

export default function RootLayout({ children }: LayoutProps<'/'>) {
  return (
    <html lang="en" className={`${inter.variable} ${jetbrainsMono.variable} h-full antialiased`}>
      <body className="min-h-full bg-neutral-950">{children}</body>
    </html>
  );
}
