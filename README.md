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

Profiles discovered in subdirectories are addressed by their path
relative to the scanned directory, for example `--profile work/foo`
for `work/foo.mplt`.

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
(extra directories can be added with `--profile-dir`).  Profile
directories are scanned recursively, so profiles may also live in
subdirectories and are treated identically wherever they are found.
Settings shared between profiles can be placed in a file named
`INCLUDE` in any profile directory (see below).

A profile is organised into sections:

```ini
[profile]
name = Work

[rules]
# Every matching rule adds its weight to the profile's score.
From = .*@company\.com
body = \[internal\]

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
``Content-Transfer-Encoding``).  Non‑ASCII characters in header bodies
are written verbatim as UTF‑8; mailplate does not RFC 2047‑encode them.

### Sections

`[profile]`
:   Profile metadata. The only field is `name`.
    If absent the filename stem is used.

`[rules]`
:   Auto‑detection rules. Each line is ``HeaderName = regex`` for a
    header rule or ``body = regex`` for the message body. Each rule is
    matched independently: every matching rule adds its weight to the
    profile's score, while a non-matching rule adds nothing. The
    profile with the highest total score wins, provided that score is
    at least 1. A rule can carry an optional weight by suffixing the
    field name with ``:weight``; the weight influences profile scoring
    and defaults to 1. Field names are matched case-insensitively. The
    field name ``body`` is reserved for the body rule, and ``rcpt`` for
    a rule matching against all of the To/Cc/Bcc headers at once (it
    applies if the regex matches any one of them). The old
    ``header = HeaderName: regex`` form (and its weighted variant) is no
    longer accepted.

    ``From:5 = .*@company\\.com``
    :   A header rule worth 5 points instead of the default 1.

    ``body:3 = urgent``
    :   A body rule worth 3 points.

    ``X-Spam-Flag:0 = (?P&lt;spam&gt;YES)``
    :   A rule worth 0 points. It does not affect the score, but its
        named captures are still available to the template.

    ``X-Spam-Flag:-100 = YES``
    :   A rule worth -100 points. A sufficiently negative weight stops
        the profile from being selected whenever the rule matches.

    Use positive weights to make some rules more important than others
    during auto-detection, a weight of 0 to collect captures without
    affecting the score, and a negative weight to disqualify a profile
    when a rule matches.

    Named capture groups in a rule&#8217;s regexp become template
    variables under the ``rule:`` namespace.  For example::

        [rules]
        From = .*@(?P&lt;domain&gt;[a-z0-9.]+)

    makes ``{{ rule:domain }}`` available in greeting, closing,
    signature, and header values. Rules are evaluated for named
    captures both during auto-detection and when a profile is selected
    explicitly with ``--profile``.

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

### Including shared settings

A file named exactly `INCLUDE` (with no extension) in a profile
directory provides settings that are automatically applied to every
profile in that directory and its subdirectories.  When
`foo/bar/prof.mplt` is loaded, the INCLUDE files are applied in order
from least to most specific — the root-level `INCLUDE`, then
`foo/INCLUDE`, then `foo/bar/INCLUDE` — followed by the profile itself.
An `INCLUDE` file uses the same format as a profile, except that it
must not contain a `[profile]` section.

`[rules]`, `[headers]`, `[helpers]`, and `[remove_headers]` accumulate
across all files; the more specific file wins on a name collision, and
verbatim duplicate rules are kept only once.  `[greeting]`,
`[closing]`, and `[signature]` are single‑valued: the most specific
file that defines the section wins.  An explicitly empty section (for
example a `[signature]` header with no lines) clears an inherited one.

`INCLUDE` files are not listed by `--list-profiles` and cannot be
selected as a profile.

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

`~/.config/mailplate/profiles/**/*.mplt`
:   User‑specific profiles (found recursively).

`/etc/mailplate/profiles/**/*.mplt`
:   System‑wide profiles (found recursively).

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
