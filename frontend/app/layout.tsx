import type { Metadata } from 'next';
import './globals.css';
export const metadata: Metadata = { title: 'ClipCut — Cada segundo importa', description: 'Seu pequeno estúdio de recortes de vídeo.' };
export default function Layout({children}: Readonly<{children: React.ReactNode}>) {
  return <html lang="pt-BR"><body>{children}</body></html>;
}
