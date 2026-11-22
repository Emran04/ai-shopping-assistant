import Link from "next/link";
import { ShoppingChat } from "../shopping-chat";
import "./catalog.css";

export default function CatalogLayout({ children }) {
  return (
    <div className="site-shell catalog-shell">
      <header className="site-header catalog-header">
        <Link className="wordmark" href="/">
          <span className="brand-mark" aria-hidden="true">e.</span>
          Ecomm Assistant
        </Link>
        <nav aria-label="Main navigation"><Link href="/catalog">Shop clothing</Link></nav>
      </header>
      {children}
      <ShoppingChat />
    </div>
  );
}
