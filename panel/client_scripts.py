"""Render the shared client script for one certificate without executing it."""

import re


VARIABLES = ("DOMAIN", "FULLCHAIN_URL", "PRIVKEY_URL")
EXAMPLE_DOMAIN = re.compile(r"(?<![a-zA-Z0-9_])example\.com(?![a-zA-Z0-9_])")
EXAMPLE_URL = re.compile(r"https?://[^\s\"'<>]+/example\.com/(fullchain|privkey)\.pem")


def assignment_pattern(name):
    return re.compile(r"(?m)^([ \t]*(?:export[ \t]+)?" + name + r"[ \t]*=)[^\n]*$")


def adaptable(content):
    domain = ("{{DOMAIN}}" in content or bool(assignment_pattern("DOMAIN").search(content))
              or bool(EXAMPLE_DOMAIN.search(content)))
    urls = "{{DOWNLOAD_BASE}}" in content or all(
        "{{" + name + "}}" in content or assignment_pattern(name).search(content)
        or any(match.group(1) == filename for match in EXAMPLE_URL.finditer(content))
        for name, filename in (("FULLCHAIN_URL", "fullchain"), ("PRIVKEY_URL", "privkey"))
    )
    return bool(content.strip() and domain and urls)


def render_script(content, domain, base):
    if not adaptable(content):
        raise ValueError("脚本需要 DOMAIN、FULLCHAIN_URL、PRIVKEY_URL 配置，或对应的模板占位符")
    # Both values come from validated domain/URL components, never from shell evaluation.
    values = {"DOMAIN": domain, "DOWNLOAD_BASE": base,
              "FULLCHAIN_URL": base + "/" + domain + "/fullchain.pem",
              "PRIVKEY_URL": base + "/" + domain + "/privkey.pem"}
    for name in VARIABLES:
        content = assignment_pattern(name).sub(lambda match: match.group(1) + '"{{' + name + '}}"', content)
    content = EXAMPLE_URL.sub(lambda match: "{{" + ("FULLCHAIN_URL" if match.group(1) == "fullchain" else "PRIVKEY_URL") + "}}", content)
    content = EXAMPLE_DOMAIN.sub("{{DOMAIN}}", content)
    return re.sub(r"\{\{(DOMAIN|DOWNLOAD_BASE|FULLCHAIN_URL|PRIVKEY_URL)\}\}",
                  lambda match: values[match.group(1)], content)
