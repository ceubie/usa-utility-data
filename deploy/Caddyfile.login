# Login proxy. Pair with REQUIRE_AUTH=1. PROXY_USER, PROXY_PASSWORD_HASH and
# PROXY_SHARED_SECRET come from the environment. Identity headers sent by a
# client are removed before the proxy sets its own.
:8080 {
	request_header -X-Forwarded-User
	request_header -X-Proxy-Secret

	basic_auth {
		{$PROXY_USER} {$PROXY_PASSWORD_HASH}
	}

	handle /api/* {
		reverse_proxy 127.0.0.1:8000 {
			header_up X-Forwarded-User {http.auth.user.id}
			header_up X-Proxy-Secret {$PROXY_SHARED_SECRET}
		}
	}

	handle {
		root * /srv
		try_files {path} /index.html
		file_server
	}
}
