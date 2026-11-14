# User-Agent profiles

Connect using a content administrator key and open Content > User-Agent management. Global settings
show the resolved fallback, maximum length, profile count, revision and last update. Enter a valid
custom string, inspect the preview and save. Restore global default clears only the global override;
service overrides/profile assignments continue to take precedence. Reload discards unsaved edits.

Create profile generates a unique ID with name, exact UA value, description and usage category. Edit
fields without a browser whitelist. Server records creation/update timestamps. Duplicate copies a
profile under a new ID; save to persist. Disable retains references but makes resolution fall back to
global/default (or another enabled rotation candidate). Delete is allowed only after all service/pool
references are removed. The API rejects dangling references transactionally; default profile is restored
if omitted and cannot be disabled or changed to another value. At most 100 profiles include the default.

Service rows show custom overrides, profile assignments and previews. A custom value wins over an
assigned profile. Clear custom value and choose Use global to unassign. Fixed operator policies lock
service controls and take priority regardless of saved values. All four actual services are listed.
Save commits the entire policy document atomically; a conflicting revision returns 409 rather than
silently overwriting another admin's changes. Validation errors are displayed without echoing input.

Automatic browser identity selection needs ADBOT_USER_AGENT_ROTATABLE_SERVICES=browser and an
explicit rotation policy/profile pool. Other service types remain nonrotating. Options: round_robin,
random, scheduled (minimum interval 30 seconds), proxy_endpoint (deterministic profile mapping from
assigned approved endpoint ID). Rotation pool must not conflict with custom/fixed profile overrides.
Disabling candidates cannot cause malformed headers; empty eligible pools use global/default.

Example POST document: revision 0, global_value "ApprovedCompatibilityClient/2", profiles containing
{id:"compat",name:"Compatibility",value:"ApprovedTest/2",enabled:true}, services containing
{browser:{profile:"compat"}}. Include current complete profile/service lists when updating. GET returns
the canonical document/revision. API endpoints do not create new integrations or authorize evasion.

Service policies also expose enabled and updated_at. Disabling an override leaves its saved settings
available for restoration but uses global/default; operator-fixed identity still wins. Saving updates
server timestamps. UA values, profile IDs and rotation pools remain validated even when disabled so
reenabling cannot unexpectedly activate malformed data.
