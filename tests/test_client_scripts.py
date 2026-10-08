import pytest

from panel.client_scripts import adaptable, render_script


def test_example_script_adapts_fixed_urls_directories_and_logs():
    template = '''#!/bin/bash
DOMAIN="example.com"
FULLCHAIN_URL="http://192.168.8.24:8081/example.com/fullchain.pem"
PRIVKEY_URL="http://192.168.8.24:8081/example.com/privkey.pem"
CERT_DIR="/home/vesoft/ssl-renewal/example.com"
LOG_FILE="/var/log/ssl-renew-example.com.log"
RENEW_BEFORE_DAYS=5
echo "${DOMAIN}"
'''
    for domain in ("alpha.example.org", "beta.example.net"):
        result = render_script(template, domain, "https://certs.example.org:9443")
        assert 'DOMAIN="' + domain + '"' in result
        assert 'FULLCHAIN_URL="https://certs.example.org:9443/' + domain + '/fullchain.pem"' in result
        assert 'PRIVKEY_URL="https://certs.example.org:9443/' + domain + '/privkey.pem"' in result
        assert '/home/vesoft/ssl-renewal/' + domain in result
        assert '/var/log/ssl-renew-' + domain + '.log' in result
        assert 'RENEW_BEFORE_DAYS=5\necho "${DOMAIN}"' in result
        assert "192.168.8.24" not in result and "example.com" not in result


def test_legacy_assignments_and_literal_example_urls():
    legacy = 'export DOMAIN="old.example.org"\nFULLCHAIN_URL="old"\nPRIVKEY_URL="old"\nCERT_DIR="/ssl/${DOMAIN}"\n'
    result = render_script(legacy, "new.example.org", "http://[::1]:8001")
    assert 'export DOMAIN="new.example.org"' in result
    assert 'http://[::1]:8001/new.example.org/privkey.pem' in result
    assert 'CERT_DIR="/ssl/${DOMAIN}"' in result
    literal = 'wget "http://old:8001/example.com/fullchain.pem"\nwget "http://old:8001/example.com/privkey.pem"\n'
    result = render_script(literal, "new.example.org", "https://certs.example.org")
    assert 'wget "https://certs.example.org/new.example.org/fullchain.pem"' in result
    assert 'wget "https://certs.example.org/new.example.org/privkey.pem"' in result


def test_download_base_placeholder():
    template = 'name="{{DOMAIN}}"\nbase="{{DOWNLOAD_BASE}}"\n'
    assert render_script(template, "example.org", "http://certs:8001") == 'name="example.org"\nbase="http://certs:8001"\n'


def test_generated_values_are_not_replaced_again():
    template = 'DOMAIN="example.com"\nFULLCHAIN_URL="old"\nPRIVKEY_URL="old"\nLOG="ssl-renew-example.com.log"'
    result = render_script(template, "app.example.com", "http://certs.example.com:8001")
    assert 'DOMAIN="app.example.com"' in result
    assert 'http://certs.example.com:8001/app.example.com/fullchain.pem' in result
    assert 'LOG="ssl-renew-app.example.com.log"' in result


@pytest.mark.parametrize("template", ["echo hello", 'DOMAIN="example.com"', 'FULLCHAIN_URL="old"\nPRIVKEY_URL="old"'])
def test_unadaptable_script_is_rejected(template):
    assert not adaptable(template)
    with pytest.raises(ValueError):
        render_script(template, "example.org", "http://certs:8001")
