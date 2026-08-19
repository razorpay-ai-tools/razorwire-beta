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
  // Both themes are supported now, so let the UA pick and give it a colour per scheme.
  themeColor: [
    { media: '(prefers-color-scheme: dark)', color: '#131415' },
    { media: '(prefers-color-scheme: light)', color: '#f7f7f7' },
  ],
  colorScheme: 'light dark',
  width: 'device-width',
  initialScale: 1,
};

export default function RootLayout({ children }: LayoutProps<'/'>) {
  return (
    /* suppressHydrationWarning: the inline script sets `data-theme` before React
       hydrates, so the server markup deliberately lacks an attribute the client has.
       Scoped to <html>, so a genuine mismatch anywhere else still reports. */
    <html
      lang="en"
      suppressHydrationWarning
      className={`${inter.variable} ${jetbrainsMono.variable} h-full antialiased`}
    >
      <head>
        {/*
         * Resolve the theme BEFORE first paint. Without this the page renders in the
         * default theme and then snaps, and any React state holding the theme would
         * disagree with the server's guess on hydration.
         */}
        <script
          dangerouslySetInnerHTML={{
            __html: `(()=>{try{var s=localStorage.getItem('razorwire-theme');document.documentElement.dataset.theme=(s==='light'||s==='dark')?s:(matchMedia('(prefers-color-scheme: light)').matches?'light':'dark')}catch(e){document.documentElement.dataset.theme='dark'}})()`,
          }}
        />
      </head>
      <body className="min-h-full bg-surface-0 text-ink">{children}</body>
    </html>
  );
}
