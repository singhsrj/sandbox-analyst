import { describe, expect, it } from "vitest";
import { replaceSandboxImages } from "../format";

describe("replaceSandboxImages", () => {
  it("turns sandbox and bare-name chart embeds into a pointer to the Files panel (found live)", () => {
    expect(replaceSandboxImages("See ![Revenue by region](/home/user/outputs/regions.png) above.")).toBe(
      "See *(Revenue by region: see regions.png in Files)* above.",
    );
    expect(replaceSandboxImages("![](return_rate_by_category.png)")).toBe(
      "*(return_rate_by_category.png: see return_rate_by_category.png in Files)*",
    );
  });

  it("leaves real web images, links and plain text alone", () => {
    const text = "![logo](https://example.com/a.png) and [report](report.md) and `![x](y)` text";
    expect(replaceSandboxImages(text)).toBe(
      "![logo](https://example.com/a.png) and [report](report.md) and `*(x: see y in Files)*` text",
    );
  });
});
