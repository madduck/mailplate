# `mailplate` Examples

## Default profile

The first profile without any rules will be considered the default profile:

```ini
[profile]
name = My Default

[headers]
X-Motto: Keep the Good Times rollin'

[closing]
Best regards,
martin

[signature]
Take care, and thanks for all the fish.
```

## Including command output

Let's say I want to include a
[`fortune` cookie](<https://en.wikipedia.org/wiki/Fortune_(Unix)>) with every
email:

```ini
[profile]
name = fortune cookie

[signature]
{{helper:fortune}}

[helpers]
fortune = fortune -s
```

## NGO profile

I work with an NGO, and when I send email within the NGO, or to our partner
organisation, I want `mailplate` to append header, the signature, and ensure my
name is always formatted properly:

```ini
[profile]
name = ngo

[rules]
rcpt:10 = @ngo\.example\.net
rcpt:5 = @partner\.example\.org
from:10 = @ngo\.example\.net

[headers]
From = Martin Krafft, CHO <martin@ngo.example.net>
Organization = NGO Inc.

[greeting]
To Whom It May Concern:

[signature]
Martin
Chief Happiness Officer
NGO Inc.
```

## Inclusions

Putting something like helper definitions, or a signature into a file `INCLUDE`
makes them available to all profiles in the folder, or any subfolder!

This is also useful if you have two "identities" in the same context, e.g.:

```ini ~/.config/mailplate/profiles/ngo/INCLUDE
[headers]
Organization: NGO Inc.

[signature]
NGO Inc.
{{helper:get_gdpr_notice}}

[helpers]
get_gdpr_notice = cat /srv/ngo/shared/gdpr_notice.txt
```

And then:

```ini ~/.config/mailplate/profiles/ngo/martin.mplt
[rules]
rcpt:10 = @ngo\.example\.net
rcpt:5 = @partner\.example\.org
from:10 = @ngo\.example\.net

[headers]
From = Martin Krafft, CHO <martin@ngo.example.net>

[closing]
Best regards,
Martin
```

and also:

```ini ~/.config/mailplate/profiles/ngo/martin.mplt
[rules]
from:12 = it-support@ngo\.example\.net

[headers]
From = Martin Krafft, IT <it-support@ngo.example.net>

[closing]
Hope this helps,
Martin
```

The latter rule will be selected over `ngo/martin` for emails sent as
`it-support@` because of the higher weight on the rule (12 > 10).

## Extracting and using header data

One of my best decisions ever was to use a catchall domain I call `pobox` for
anyone and anything wanting my email address. If I need to fill in a form on
`example.org`, I use `example.org@pobox.example.net`.

The following profile ensures that when I reply to an email received there, it
uses the appropriate local part.

```ini
[profile]
name = pobox

[rules]
rcpt:0 = @(?P<domain>[-=.\w]+)
from:12 = (?P<pbxdomain>[-=.\w]+)@pobox\.example\.net

[headers]
From = Martin Krafft <{{rule:pbxdomain|default(rule:domain)}}@pobox.example.net>

[signature]
Notice about the sender address used
> Strange sender address? Yes, {{rule:pmndomain|default(rule:domain)}}@pobox.…
> must look weird, but it works, and allows me to keep our correspondence
> separate. It does not mean I am affiliated with your organisation.
```

The `rcpt:0` rule furthermore allows me to invoke `mailplate -p pobox`, and it
will attempt to extract the recipient domain, and use that in the `From` header.
