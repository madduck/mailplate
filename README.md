# mailplate

**mailplate** is a Unix‑style filter for [RFC 5322][] email drafts.
It reads a draft from standard input, rewrites it according to a **Profile**,
and writes the result to standard output (or to a file with `--output`).

It is designed to integrate with text‑based mail user agents such as Mutt.

[RFC 5322]: https://www.rfc-editor.org/rfc/rfc5322

## Installation

```sh
uv tool install mailplate
```

Or from a checkout:

```sh
uv sync
uv run mailplate --help
```

## Usage

### Explicit profile

```sh
mailplate --profile work < draft.eml > rewritten.eml
```

### Auto‑detection

Omit `--profile`. mailplate scans available profiles, applies each
profile’s rules against the input message, and picks the profile with
the most matching rules. Profiles with no rules act as catch‑alls
(score 0, selected only if no rule‑based profile matches).

```sh
mailplate < draft.eml > rewritten.eml
```

### List available profiles

```sh
mailplate --list-profiles
```

### Verbose logging

```sh
mailplate --verbose < draft.eml
```

Prints diagnostic information to stderr: profile search paths,
discovery counts, per‑rule match/fail for every candidate,
selection rationale, and byte counts for reads and writes.

### In‑place replacement (via temporary file)

```sh
mailplate --output draft.eml < draft.eml
```

## Profile format

Profiles are flat text files with a `.mplt` extension, stored in
`~/.config/mailplate/profiles/` or `/etc/mailplate/profiles/`
(extra directories can be added with `--profile-dir`).

A profile is organised into sections:

```ini
[profile]
name = Work

[rules]
# All rules must match (AND logic).
header = From:.*@company\.com
body   = \[internal\]

[headers]
X-Mailer = mailplate/1.0

[greeting]
Hi {{ to_name | default("there") }},

[closing]
Best regards,
{{ from_name }}

[signature]
{{ from_name }}
{{ from_email }}
My Company Inc.
```

mailplate only handles **plain‑text** drafts — messages that contain
anything other than ``text/plain`` (e.g. HTML parts, attachments) are
rejected with an error.  The output is a bare RFC 5322 message without
MIME headers (no ``MIME-Version``, ``Content-Type``, or
``Content-Transfer-Encoding``).

### Sections

`[profile]`
:   Profile metadata. The only field is `name`.
    If absent the filename stem is used.

`[rules]`
:   Auto‑detection rules. Each line is ``header = HeaderName: regex`` or
    ``body = regex``. All rules inside a profile must match for the
    profile to be selected (AND semantics). Rules can carry an optional
    weight that influences profile scoring.

    ``header:5 = From:.*@company\\.com``
    :   A header rule worth 5 points instead of the default 1.

    ``body:3 = urgent``
    :   A body rule worth 3 points.

    The profile with the highest total score wins. Use weights to make
    some rules more important than others during auto-detection.

    Named capture groups in a rule&#8217;s regexp become template
    variables under the ``rule:`` namespace.  For example::

        [rules]
        header = From:.*@(?P&lt;domain&gt;[a-z0-9.]+)

    makes ``{{ rule:domain }}`` available in greeting, closing,
    signature, and header values.

`[headers]`
:   Header definitions. Each line is `Header‑Name = value`.
    Existing headers with the same name (case‑insensitive) are
    replaced. Template placeholders (see below) are expanded.

    Header values can reference other headers via
    ``{{ header:<Name> }}`` and the ``{{ subject }}``, ``{{ from }}``,
    etc. shorthand variables.

`[greeting]`
:   Lines inserted before the original body. A blank line between
    sections is provided automatically. Template variables are
    expanded.

`[closing]`
:   Lines inserted after the original body but before the signature.
    Template variables are expanded.

`[signature]`
:   Lines appended at the end of the message. Template variables are
    expanded. The signature is separated from the closing by a
    ``^-- $`` delimiter line.

    If the original draft already contains a signature (i.e. text
    following a ``^-- $`` line), that signature is replaced by the
    profile&#8217;s ``[signature]`` section. If the profile does not
    define a ``[signature]`` section, the original draft signature
    is preserved unchanged.

    Greeting and closing idempotency (see below) applies only to the
    body portion; the signature is never touched by that logic.

`[remove_headers]`
:   One header name per line; matching headers (case‑insensitive) are
    deleted from the output. Takes effect after ``[headers]`` have been set.

`[helpers]`
:   External command definitions. Each line is ``name = shell command``.
    The command is invoked with :func:`shlex.split` and :func:`subprocess.run`
    with a 5‑second timeout. Use ``{{ helper:<name> }}`` in template
    sections to insert the command&#8217;s stdout::

        [helpers]
        get_quote    = fortune -n2
        get_long_date = date '+%d %B %Y'

Comments start with `#` and blank lines are ignored.

### Idempotency

If the body already starts with the rendered greeting and/or ends with
the rendered closing + signature block, those are stripped before the
fresh decorations are applied. Running `mailplate` multiple times with
the same profile therefore does not keep piling on extra greeting or
closing lines.

## Template variables

| Variable              | Description                                         |
| --------------------- | --------------------------------------------------- |
| `{{ body }}`          | Original plain‑text body                            |
| `{{ from }}`          | Full `From` header value                            |
| `{{ from_name }}`     | Display‑name part of `From`                         |
| `{{ from_email }}`    | Email‑address part of `From`                        |
| `{{ to }}`            | Full `To` header value                              |
| `{{ to_name }}`       | Display‑name part of the first `To` address         |
| `{{ to_email }}`      | Email‑address part of the first `To` address        |
| `{{ subject }}`       | `Subject` header value                              |
| `{{ date }}`          | `Date` header value                                 |
| `{{ header:<Name> }}` | Value of an arbitrary header                        |
| `{{ env:<VAR> }}`     | Value of an environment variable                    |
| `{{ helper:<name> }}` | Output of a helper command defined in ``[helpers]`` |
| `{{ rule:<capture> }}` | Named regexp group from a matching rule              |

### Filters

`{{ variable | default("fallback") }}`
:   If *variable* is empty, use *fallback* instead.

## Files

`~/.config/mailplate/profiles/*.mplt`
:   User‑specific profiles.

`/etc/mailplate/profiles/*.mplt`
:   System‑wide profiles.

## Exit status

0
:   Successful completion.

1
:   An error occurred (profile not found, no input data, etc.).

## Version

```
mailplate --version
```

## Migration

If you have existing profiles from an older version of mailplate, a
migration script is provided:

```sh
uv run python3 scripts/migrate_templates.py
```

This reads templates from ``~/.mailplate/templates/`` and the helper
configuration from ``~/.mailplate/config`` and writes ``.mplt`` files
to the project&#8217;s ``profiles/`` directory. After migration, copy
them to ``~/.config/mailplate/profiles/`` or point ``--profile-dir`` at
the output directory.

## License

Distributed under the terms of the MIT license.
