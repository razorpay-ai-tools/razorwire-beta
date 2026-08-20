import type { Metadata, Viewport } from 'next';
import Image from 'next/image';
import Script from 'next/script';
import './globals.css';

export const metadata: Metadata = {
  // Cased as the header and the intro word render it.
  title: 'RazorWire',
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
      className="h-full antialiased"
    >
      <body className="min-h-full bg-surface-0 text-ink">
        {/*
         * Resolve the theme BEFORE first paint. Without this the page renders in the
         * default theme and then snaps, and any React state holding the theme would
         * disagree with the server's guess on hydration.
         *
         * `next/script` with `beforeInteractive`, not a bare `<script>` in `<head>`.
         * React 19 renders children on the client too, where a script element never
         * executes, and says so in the console. This strategy is injected into the
         * initial HTML by the server — which is the only place it can run early enough
         * — and must live in the root layout. See node_modules/next/dist/docs →
         * 01-app/03-api-reference/02-components/script.md.
         */}
        <Script id="theme-bootstrap" strategy="beforeInteractive">
          {`(()=>{try{var s=localStorage.getItem('razorwire-theme');document.documentElement.dataset.theme=(s==='light'||s==='dark')?s:(matchMedia('(prefers-color-scheme: light)').matches?'light':'dark')}catch(e){document.documentElement.dataset.theme='dark'}})()`}
        </Script>

        {/*
         * The intro. Here rather than in page.tsx because the root layout is the only
         * place it lands in the server's first HTML — see the recipe in globals.css.
         * aria-hidden: it says nothing the <title> and the header do not already say.
         * `preload`, not the Next 16-deprecated `priority` — this logo IS the LCP
         * element for the first ~1.8s, so its <link> belongs in <head>.
         */}
        <div className="intro" aria-hidden>
          <Image
            src="/razorwire-logo.png"
            alt=""
            width={72}
            height={72}
            preload
            className="intro-mark size-[72px]"
          />
          <span className="intro-word">RazorWire</span>
        </div>

        {children}
      </body>
    </html>
  );
}
