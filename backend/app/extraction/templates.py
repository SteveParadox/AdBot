"""Editable schema seeds, not claims of universal website compatibility."""

from .schemas import SchemaDefinition


def field(kind="string", path="", required=False, method="jsonld", **extra):
    return dict(type=kind, path=path, required=required, method=method, **extra)


TEMPLATES = {
    "products": dict(
        name="Products",
        record_method="jsonld",
        jsonld_type="Product",
        identity_fields=["product_url"],
        fields={
            "name": field(path="name", required=True),
            "description": field(path="description"),
            "price": field("currency", "offers.price"),
            "currency": field(path="offers.priceCurrency", transformations=["currency_code"]),
            "availability": field(path="offers.availability"),
            "brand": field(path="brand.name"),
            "identifier": field(path="sku"),
            "rating": field("decimal", "aggregateRating.ratingValue"),
            "product_url": field("url", "url", True),
            "images": field("list", "image"),
        },
    ),
    "jobs": dict(
        name="Job listings",
        record_method="jsonld",
        jsonld_type="JobPosting",
        identity_fields=["application_url"],
        fields={
            "title": field(path="title", required=True),
            "company": field(path="hiringOrganization.name"),
            "location": field("object", "jobLocation"),
            "remote_classification": field(path="jobLocationType"),
            "employment_type": field(path="employmentType"),
            "salary": field("object", "baseSalary"),
            "currency": field(path="baseSalary.currency", transformations=["currency_code"]),
            "description": field(path="description"),
            "application_url": field("url", "url", True),
            "publication_date": field("date", "datePosted"),
            "source_url": field("url", method="source_url"),
        },
    ),
    "articles": dict(
        name="Articles",
        record_method="jsonld",
        jsonld_type="Article",
        identity_fields=["canonical_url"],
        fields={
            "headline": field(path="headline", required=True),
            "author": field(path="author.name"),
            "publication_date": field("datetime", "datePublished"),
            "updated_date": field("datetime", "dateModified"),
            "publisher": field(path="publisher.name"),
            "category": field(path="articleSection"),
            "body": field(path="articleBody", max_length=20000),
            "canonical_url": field("url", "url", True),
            "featured_image": field("url", "image.url"),
            "source_metadata": field("string", "@type"),
        },
    ),
    "businesses": dict(
        name="Public business directory",
        record_method="jsonld",
        jsonld_type="LocalBusiness",
        identity_fields=["website"],
        fields={
            "name": field(path="name", required=True),
            "address": field("object", "address"),
            "public_business_telephone": field(path="telephone"),
            "website": field("url", "url", True),
            "category": field(path="@type"),
            "description": field(path="description"),
            "opening_hours": field(path="openingHours"),
            "source_url": field("url", method="source_url"),
        },
    ),
    "monitoring": dict(
        name="Website content monitoring",
        identity_fields=["url"],
        fields={
            "url": field("url", method="source_url", required=True),
            "title": field(method="page_title"),
            "content": field(method="css", selector="main", required=True, max_length=20000),
        },
    ),
}


def templates():
    return [
        {"id": key, "definition": SchemaDefinition.model_validate(value).model_dump()}
        for key, value in TEMPLATES.items()
    ]
