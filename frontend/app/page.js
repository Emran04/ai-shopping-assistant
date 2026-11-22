import Link from "next/link";
import { ShoppingChat } from "./shopping-chat";

export default function Home() {
  return (
    <div className="site-shell">
      <header className="site-header home-header">
        <div className="wordmark">
          <span className="brand-mark" aria-hidden="true">e.</span>
          Ecomm Assistant
        </div>
        <nav aria-label="Main navigation"><Link href="/catalog">Shop clothing</Link></nav>
      </header>

      <main className="workspace">
        <section className="intro" aria-labelledby="page-title">
          <h1 id="page-title">What are you<br className="desktop-break" /> shopping for?</h1>
          <p>Ask what to look for, compare options, or find a gift that fits your budget.</p>
        </section>
        <ShoppingChat />
      </main>
    </div>
  );
}
