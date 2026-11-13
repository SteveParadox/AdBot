# Domain and identity privacy

Use accurate registration and business information. Do not fabricate identities, conceal required
beneficial ownership or remove legal disclosures. This document is operational guidance; determine
jurisdiction-specific disclosure duties with a qualified adviser before changing legal contact details.

## Registrar and DNS
Use a registrar's WHOIS/RDAP privacy or redaction service when eligible for the domain/TLD; inspect
public RDAP output after activation. Privacy availability, fees and verification vary. Keep the registrar's
underlying contacts accurate and promptly complete verification requests. Use role-based business email
and appropriate business technical contacts, not a fake registrant. Public data redaction is not deletion
of registrar records, escrow data, historical WHOIS/DNS or certificate transparency records.
[ICANN accuracy requirements](https://www.icann.org/resources/pages/registration-data-accurate-2023-11-02-en)
and [registration data policy](https://www.icann.org/resources/pages/registration-data-policy-2024-02-21-en/).

## Public identity
Use verified business support mailboxes and dedicated support phone numbers. Keep personal accounts
separate and enable MFA and recovery controls. Use a legitimate business service address where legally
permissible, retaining any required registered-office/contact disclosures. Review the public CMS, SEO,
image metadata, PDFs, support responses and third-party directory listings. Public business information
can be maintained in published content sections; no personal values were invented by this implementation.
Keep dependency notices, copyright attribution, legitimate ownership records and Git history intact.

## Infrastructure
Proxy eligible web records, protect the origin with Tunnel or allowlisting plus TLS authentication, and
separate mail/other services that reveal the same origin IP. Audit A/AAAA/CNAME/MX/TXT/SPF records and
stale subdomains. A CDN cannot erase historical IP exposure. Consider a new origin address only after
eliminating leaks and safely migrating services. Restrict operator access via VPN/bastion and test a
recovery path. Email providers, payment processors, monitoring tools and public uploaded assets may
reveal business or infrastructure details independently. Review their settings and log retention too.

These controls do not guarantee anonymity from registrars, hosting providers, financial institutions,
payment processors, regulators, lawful investigations or legally public corporate registries. They reduce
unnecessary public disclosure while preserving accountability and truthful business representation.
