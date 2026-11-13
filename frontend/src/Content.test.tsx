import { describe, expect, it } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import { ContentBlock } from "./Content";

describe("published content rendering", () => {
  it("renders text as escaped content with accessible media and links", () => {
    const html = renderToStaticMarkup(<ContentBlock data={{title:"Offer",description:"<script>alert(1)</script>",image:"/offer.png",image_alt:"Offer details",link:"/details",button:"View details"}} />);
    expect(html).toContain("&lt;script&gt;");
    expect(html).not.toContain("<script>");
    expect(html).toContain('alt="Offer details"');
    expect(html).toContain('loading="lazy"');
    expect(html).toContain('href="/details"');
  });
  it("handles an empty section", () => {
    const html = renderToStaticMarkup(<ContentBlock data={{}} />);
    expect(html).not.toContain("<img");
    expect(html).not.toContain("<a ");
  });
});
