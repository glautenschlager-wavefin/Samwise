import truststore

# Use the OS certificate store (macOS Keychain, Windows cert store, etc.)
# so corporate proxy / VPN CAs are trusted by all httpx clients.
truststore.inject_into_ssl()
