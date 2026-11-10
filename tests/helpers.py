"""Submit invoices with the revision actually offered by their issuer's form."""
from lxml import html


def write_invoice_pdf(document):
    """Replace placeholder PDF bytes with a real attachment matching the fixture."""
    import json

    from zugferd import build_xml

    sidecar = document.with_suffix(".json")
    data = json.loads(sidecar.read_bytes())
    data.setdefault("seller", {"name": "Test Seller", "country": "DE"})
    data.setdefault("buyer", {"name": "Test Customer", "country": "DE"})
    data["buyer"].setdefault("name", "Test Customer")
    data["buyer"].setdefault("country", "DE")
    data["invoice"].setdefault("tax_treatment", "de_19")
    for item in data["items"]:
        item.setdefault("description", "Test")
    sidecar.write_text(json.dumps(data))
    document.write_bytes(pdf_with_xml(build_xml(data)))


def pdf_with_xml(xml):
    import io

    from pypdf import PdfWriter

    writer = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    if xml is not None:
        writer.add_attachment("factur-x.xml", xml)
    stream = io.BytesIO()
    writer.write(stream)
    return stream.getvalue()


def export_invoice(client, *, data, query_string=None, follow_redirects=False):
    context = {**(query_string or {}), **data}
    context = {key: context[key] for key in ("issuer", "correction_source", "doc_type") if key in context}
    response = client.get("/", query_string=context)
    fields = data.copy()
    if response.status_code == 200:
        page = html.fromstring(response.data)
        fields["seller_revision"] = page.xpath('//*[@id="invoice-form"]/input[@name="seller_revision"]/@value')[0]
    return confirmed_post(client, "/generate", data=fields, query_string=query_string, follow_redirects=follow_redirects)


def confirmed_post(client, *args, **kwargs):
    """Simulate a user approving the exact proposed change in lifecycle tests.

    Confirmation-specific tests deliberately use the raw Flask client instead.
    Approve at most once: a changed state or request must still surface as 428.
    """
    response = client.post(*args, **kwargs)
    if response.status_code != 428:
        return response
    if response.is_json:
        token = response.json['confirmation']['token']
    else:
        page = html.fromstring(response.data)
        token = page.xpath('//input[@name="_change_confirmation"]/@value')[0]
    headers = dict(kwargs.get('headers') or {})
    headers['X-Change-Confirmation'] = token
    return client.post(*args, **{**kwargs, 'headers': headers})
