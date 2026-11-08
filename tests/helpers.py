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
    return confirmed_post(client, "/generate", data=fields, query_string=query_string)


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
