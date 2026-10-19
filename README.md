# mailplate

**mailplate** is a Unix‑style filter for email drafts. It can integrate with a
mail user agent, such as [Mutt](http://mutt.org), to provide rule-based and
manual **control over your email identity**, i.e. the signature to use in a
given context, which headers to set, and how to greet your reader.

It reads a draft from standard input, rewrites it according to a (manually or
automatically selected) **Profile**, and writes the result to standard output
(or to a file with `--output`).

## Installation

<!--
```sh
uv tool install mailplate
```

Or from a checkout:
-->

I am working on publishing `mailplate` on Pypi. Until that's successful, please
run it from a checkout:

```sh
git clone https://github.com/madduck/mailplate
cd mailplate
uv sync
uv run mailplate --help
```

or install it (to `~/.local/bin` by default) as follows:

```sh
git clone https://github.com/madduck/mailplate
cd mailplate
uv tool install .
```

## Examples

In [Examples.md](https://github.com/madduck/mailplate), you may find a couple of
examples for your use and idea generation.

## Usage with Mutt & Neomutt

While `mailplate` may be useful as a CLI by itself (see "Usage as CLI" below),
it was primarly designed to integrate with the [Mutt MUA](http://mutt.org/), and
its descendents, such as [Neomutt](https://neomutt.org/).

### Integrating with `$editor` to auto-detect profile

If your editor is "Vim", then the following integrates `mailplate` with your
MUA:

```Muttrc
set edit_headers=yes
set editor="vim -c '%!mailplate --quiet'"
```

If you use `vi`, replace with `vi`; If you use Neovim, replace with `nvim`.

You need `$edit_headers` so that Mutt makes an email draft available; Otherwise
its just a text file, without access to header information.

In the above, Vim will be spawned and the buffer run through `mailplate`,
causing `mailplate` to analyse the draft, and rewrite it according to the
profile rules.

### Integrating with Vim for explicit profile selection

If you want to be able to change profiles from within Vim (and descendants), you
could provide key maps to similarly invoke `mailplate --profile`:

Here is some Lua inspiration for Neovim, to put into `after/ftplugin/mail.lua`:

```Lua
vim.keymap.set("n", "<leader>p", "",
  { buffer = true, desc = "mailplate profiles" }
)

vim.keymap.set(
  "n",
  "<leader>pp",
  ":w<CR>:%!mailplate<CR>",
  { buffer = true, desc = "Automatically determine mailplate profile" }
)

local function profile_keymap(key, profile)
  vim.keymap.set(
    "n",
    "<leader>p<" .. key .. ">",
    ":w<CR>:%!mailplate --profile " .. profile .. "<CR>",
    { buffer = true, desc = "Switch to mailplate profile '" .. profile .. "'" }
  )
end

profile_keymap("F1", "private")
profile_keymap("F2", "work")
profile_keymap("F3", "club")
```

and how if you press `<leader>p<F3>`, the mail draft is changed to the Profile
you use when doing work for your club.

## Usage as CLI

### Explicit profile

```sh
mailplate --profile work < draft.eml > rewritten.eml
```

Profiles discovered in subdirectories are addressed by their path relative to
the scanned directory, for example `--profile work/foo` for `work/foo.mplt`.

### Auto‑detection

Omit `--profile`. mailplate scans available profiles, applies each profile’s
rules against the input message, and picks the profile with the most matching
rules. Profiles with no rules act as catch‑alls (score 0, selected only if no
rule‑based profile matches).

```sh
mailplate < draft.eml > rewritten.eml
```

### Start from an empty draft

An empty standard input is not an error. mailplate then starts from a minimal
RFC 5322 message (a single `Content-Type: text/plain` header) and applies the
selected profile to it:

```sh
printf '' | mailplate --profile work
```

If no profile is selected in that case, the minimal message is written
unchanged.

### List available profiles

```sh
mailplate --list-profiles
```

### Logging

Diagnostics are written to standard error:

- `-v` / `--verbose` prints progress at INFO level.
- `-vv` or `--debug` prints per‑rule and capture detail at DEBUG level.
- `-q` / `--quiet` prints only errors, hiding warnings.

```sh
mailplate -vv < draft.eml
```

DEBUG output includes the profile search paths, discovery counts, per‑rule
match/fail for every candidate, captured text, the selection rationale, and byte
counts for reads and writes.

### In‑place replacement (via temporary file)

```sh
mailplate --output draft.eml < draft.eml
```

## Profile format

Profiles are flat text files with a `.mplt` extension, stored in
`$XDG_CONFIG_HOME/mailplate/profiles/` or `/etc/mailplate/profiles/` (extra
directories can be added with `--profile-dir`). When `$XDG_CONFIG_HOME` is not
set, mailplate falls back to the XDG default configuration directory
`~/.config`. Profile directories are scanned recursively, so profiles may also
live in subdirectories and are treated identically wherever they are found.
Settings shared between profiles can be placed in a file named `INCLUDE` in any
profile directory (see below).

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

mailplate only handles **plain‑text** drafts — messages that contain anything
other than `text/plain` (e.g. HTML parts, attachments) are rejected with an
error. The output is a bare RFC 5322 message without MIME headers (no
`MIME-Version`, `Content-Type`, or `Content-Transfer-Encoding`). Non‑ASCII
characters in header bodies are written verbatim as UTF‑8; mailplate does not
RFC 2047‑encode them, as the output is expected to be further processed by a
MUA, such as Mutt.

### Header order

The output always starts with these headers, in this order:

```text
From:
To:
Cc:
Bcc:
Reply-To:
Subject:
Message-ID:
```

<!-- markdownlint-disable MD038 -->

Any of them that is set neither by the input nor by the profile is still
written, with an empty value (note the space after the colon: `Cc: `). This
keeps the line numbers of a draft stable, which is what editors rely on when
they place the cursor or apply `mailplate` from within a `:%!` filter.

<!-- markdownlint-enable MD038 -->

All other headers follow in the order of the input, with headers added by the
profile at the end. Removing one of the seven headers above with
`[remove_headers]` drops its value, but the header is still written empty.

### Sections

#### `[profile]`

Profile metadata. The only field is `name`. If absent the filename stem is used.

#### `[rules]`

Auto‑detection rules. Each line is `HeaderName = regex` for a header rule or
`body = regex` for the message body. Each rule is matched independently: every
matching rule adds its weight to the profile's score, while a non-matching rule
adds nothing. The profile with the highest total score wins, provided that score
is at least 1. A rule can carry an optional weight by suffixing the field name
with `:weight`; the weight influences profile scoring and defaults to 1. Field
names are matched case-insensitively. The field name `body` is reserved for the
body rule, and `rcpt` for a rule matching against all of the To/Cc/Bcc headers
at once (it applies if the regex matches any one of them). The old
`header = HeaderName: regex` form (and its weighted variant) is no longer
accepted.

For example:

- `From:5 = .*@company\.com` — a header rule worth 5 points instead of the
  default 1.
- `body:3 = urgent` — a body rule worth 3 points.
- `X-Spam-Flag:0 = (?P<spam>YES)` — a rule worth 0 points. It does not affect
  the score, but its named captures are still available to the template.
- `X-Spam-Flag:-100 = YES` — a rule worth -100 points. A sufficiently negative
  weight stops the profile from being selected whenever the rule matches.

Use positive weights to make some rules more important than others during
auto-detection, a weight of 0 to collect captures without affecting the score,
and a negative weight to disqualify a profile when a rule matches.

Named capture groups in a rule’s regexp become template variables under the
`rule:` namespace. For example:

```ini
[rules]
From = .*@(?P<domain>[a-z0-9.]+)
```

makes `{{ rule:domain }}` available in greeting, closing, signature, and header
values. Rules are evaluated for named captures both during auto-detection and
when a profile is selected explicitly with `--profile`.

#### `[headers]`

Header definitions. Each line is `Header‑Name = value`. Existing headers with
the same name (case‑insensitive) are replaced. Template placeholders (see below)
are expanded. The seven headers listed under “Header order” above always take
their canonical position and spelling, whatever spelling the profile uses.

Header values can reference other headers via `{{ header:<Name> }}` and the
`{{ subject }}`, `{{ from }}`, etc. shorthand variables.

#### `[greeting]`

Lines inserted before the original body. A blank line between sections is
provided automatically. Template variables are expanded.

#### `[closing]`

Lines inserted after the original body but before the signature. Template
variables are expanded.

#### `[signature]`

Lines appended at the end of the message. Template variables are expanded. The
signature is separated from the body by a blank line followed by a `^-- $`
delimiter line. If the body already ends with a blank line, no extra blank line
is added.

<!-- markdownlint-disable MD038 -->

The message body always keeps at least one line, so that it is framed by a blank
line above and below. An empty draft gains that blank line, and a draft with a
signature gains a second one before the `-- ` delimiter. The last line of the
output always ends with a newline, so the draft is ready for more typing.

<!-- markdownlint-enable MD038 -->

The lines of the `[signature]` section are copied verbatim: leading whitespace
and blank lines are preserved exactly as written in the profile.

If the original draft already contains a signature (i.e. text following a
`^-- $` line), that signature is replaced by the profile’s `[signature]`
section. If the profile does not define a `[signature]` section, the original
draft signature is preserved unchanged.

Greeting and closing idempotency (see below) applies only to the body portion;
the signature is never touched by that logic.

#### `[remove_headers]`

One header name per line; matching headers (case‑insensitive) are deleted from
the output. Takes effect after `[headers]` have been set.

#### `[helpers]`

External command definitions. Each line is `name = shell command`. The command
is invoked with `shlex.split` and `subprocess.run` with a 5‑second timeout. Use
`{{ helper:<name> }}` in template sections to insert the command’s stdout:

```ini
[helpers]
get_quote     = fortune -n2
get_long_date = date '+%d %B %Y'
```

Comments start with `#` and blank lines are ignored, except inside
`[signature]`, whose content is preserved verbatim.

### Including shared settings

A file named exactly `INCLUDE` (with no extension) in a profile directory
provides settings that are automatically applied to every profile in that
directory and its subdirectories. When `foo/bar/prof.mplt` is loaded, the
INCLUDE files are applied in order from least to most specific — the root-level
`INCLUDE`, then `foo/INCLUDE`, then `foo/bar/INCLUDE` — followed by the profile
itself. An `INCLUDE` file uses the same format as a profile, except that it must
not contain a `[profile]` section.

`[rules]`, `[headers]`, `[helpers]`, and `[remove_headers]` accumulate across
all files; the more specific file wins on a name collision, and verbatim
duplicate rules are kept only once. `[greeting]`, `[closing]`, and `[signature]`
are single‑valued: the most specific file that defines the section wins. An
explicitly empty section (for example a `[signature]` header with no lines)
clears an inherited one.

`INCLUDE` files are not listed by `--list-profiles` and cannot be selected as a
profile.

### Idempotency

If the body already starts with the rendered greeting and/or ends with the
rendered closing + signature block, those are stripped before the fresh
decorations are applied. Running `mailplate` multiple times with the same
profile therefore does not keep piling on extra greeting or closing lines.

## Template variables

| Variable               | Description                                       |
| ---------------------- | ------------------------------------------------- |
| `{{ body }}`           | Original plain‑text body                          |
| `{{ from }}`           | Full `From` header value                          |
| `{{ from_name }}`      | Display‑name part of `From`                       |
| `{{ from_email }}`     | Email‑address part of `From`                      |
| `{{ to }}`             | Full `To` header value                            |
| `{{ to_name }}`        | Display‑name part of the first `To` address       |
| `{{ to_email }}`       | Email‑address part of the first `To` address      |
| `{{ subject }}`        | `Subject` header value                            |
| `{{ date }}`           | `Date` header value                               |
| `{{ header:<Name> }}`  | Value of an arbitrary header                      |
| `{{ env:<VAR> }}`      | Value of an environment variable                  |
| `{{ helper:<name> }}`  | Output of a helper command defined in `[helpers]` |
| `{{ rule:<capture> }}` | Named regexp group from a matching rule           |

### Filters

`{{ variable | default(fallback) }}` — if _variable_ is empty, use _fallback_
instead. A quoted _fallback_ (`default("there")`) is a literal string; an
unquoted one (`default(rule:domain)`) is a variable reference.

Filters are applied from left to right, so several fallbacks can be chained:

`{{ rule:pmndomain | default(rule:domain) | default("example.net") }}`

`default` is the only filter mailplate provides. The template engine supports a
small subset of template syntax and is not a Jinja2 implementation.

## Files

- `$XDG_CONFIG_HOME/mailplate/profiles/**/*.mplt` — user‑specific profiles
  (found recursively).
- `/etc/mailplate/profiles/**/*.mplt` — system‑wide profiles (found
  recursively).
- [Examples](https://github.com/madduck/mailplate) — some ideas for you.

## Man page

The manual page is written in POD in `mailplate.pod`. `uv build` renders it to
`mailplate.1` with `pod2man` and installs it under `share/man/man1/` in the
wheel. The generated `mailplate.1` is a build artefact and is not tracked by
Git.

To render and preview the man page without building the package:

```sh
pod2man --section=1 --center="User Commands" --release=mailplate \
    --name=mailplate mailplate.pod | man -l -
```

## Ancestry

`mailplate` was born in the late 90s as a shell script, which I no longer have.
In 2007, I hacked up a Python script to do much of the same, as well as some of
the fancy other stuff, such as being able to use rule captures or command output
in template tags. This
[spaghetti code](https://en.wikipedia.org/wiki/Spaghetti_code) has been rotting
[on my personal Git server](https://git.madduck.net/code/mailplate.git), while
the desire to rewrite it properly has been expressed in my To-do list for years.

Then, [Carlo](https://zottmann.dev) told me about [Pi](https://pi.dev) over
lunch one day, and a few hours later, a new `mailplate` was born and has entered
my daily workflow. It's my first vibe-coded project, and I welcome your
constructive feedback and criticism. I would like to believe that this is not
"slop" due to my experience in software engineering, and the ancestry of
`mailplate`.

## Migration

If you have existing profiles from the
[spaghetti-coded version of mailplate](https://git.madduck.net/code/mailplate.git),
a migration script is provided:

```sh
uv run python3 scripts/migrate_templates.py
```

This reads templates from `~/.mailplate/templates/` and the helper configuration
from `~/.mailplate/config` and writes `.mplt` files to the project’s `profiles/`
directory. After migration, copy them to `$XDG_CONFIG_HOME/mailplate/profiles/`
or point `--profile-dir` at the output directory.

It does a pretty good job, but will likely fail on any rule that is more
complext than a simple regexp.

## License & Copyright

Distributed under the terms of the MIT license.

© 199x–2026 martin f. krafft <mailplate@pobox.madduck.net>
