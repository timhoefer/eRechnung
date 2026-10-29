"""Submit invoices with the revision actually offered by their issuer's form."""
from lxml import html


def export_invoice(client, *, data, query_string=None):
    context = {**(query_string or {}), **data}
    context = {key: context[key] for key in ("issuer", "correction_source", "doc_type") if key in context}
    response = client.get("/", query_string=context)
    fields = data.copy()
    if response.status_code == 200:
        page = html.fromstring(response.data)
        fields["seller_revision"] = page.xpath('//*[@id="invoice-form"]/input[@name="seller_revision"]/@value')[0]
    return client.post("/generate", data=fields, query_string=query_string)
