import "./globals.css";
import "./catalog/catalog-product-card.css";

export const metadata = {
  title: "Ecomm Assistant",
  description: "Ask a shopping question or compare your options.",
};

export default function RootLayout({ children }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
