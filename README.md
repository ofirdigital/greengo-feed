# Green Go Energy: OpenAI (ChatGPT) Ads product feed

Converts the WooCommerce / CTX Feed Google Merchant XML into an OpenAI-format CSV
that ChatGPT Ads Manager accepts (XML / RSS is not accepted on any path).

## Files
- `build_openai_feed.py`  the converter (stdlib only, Python 3.9+)
- `greengo_openai_ads_feed.csv`  ready-to-upload output (Upload CSV or TXT in Ads Manager)
- `report.txt`  what was fixed / dropped in the last build
- `.github/workflows/build-feed.yml`  rebuilds twice a day and commits `docs/products.csv`
  (serve `docs/` with GitHub Pages and paste the resulting HTTPS URL as the feed's Hosted URL)
- `labels.csv` (optional, create it)  `item_id,custom_label_0` to carry product groups A-D into `ads_metadata`

## What the converter does to the XML data
- `id` -> `item_id`; variants get `group_id` + `listing_has_variations=true` + `variant_dict` parsed from the `?attribute_...` query of the product link
- price `1,399.00 ILS` -> `1399.00 ILS` (thousands separators are rejected by OpenAI)
- `sale_price` kept only when strictly lower than `price` (CTX writes price into sale_price when there is no sale)
- empty descriptions (variations) -> parent description, else title + category path
- `brand` "Co" (placeholder) -> Samsung SDI / Molicel / Panasonic when the category says so, otherwise Green Go Energy (edit `BRAND_RULES` / `DEFAULT_BRAND`)
- image URLs with Hebrew characters are percent-encoded
- `seller_name` / `seller_url` added (required by the OpenAI format)
- `is_ads_eligible=true` on every row; out-of-stock rows are kept with `availability=out_of_stock` (use `--skip-out-of-stock` to drop them)

## Hosted URL setup (GitHub Pages)
1. New private-or-public repo, push these files.
2. Settings > Pages > Source: Deploy from branch, folder `/docs`.
3. Run the workflow once (Actions > Build OpenAI Ads feed > Run workflow).
4. In Ads Manager: Add new product feed > Hosted URL > `https://ofirdigital.github.io/greengo-feed/products.csv`.
