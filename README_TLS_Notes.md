# RabbitMQ Infrastructure and TLS Configuration

## Overview

DroneNav uses RabbitMQ as the message broker between application components, including NAVProxy and the telemetry infrastructure.

The production RabbitMQ broker runs in Docker on the `lochness` VPS.

Production clients connect directly to RabbitMQ using AMQP over TLS:

```text
raptor
   |
   | AMQPS / TLS
   | TCP 5671
   v
rabbitmq.dronenav.org
   |
   v
lochness
   |
   v
RabbitMQ Docker container
```

The production RabbitMQ hostname is:

```text
rabbitmq.dronenav.org
```

DNS resolves this hostname to the public IP address of `lochness`.

---

## RabbitMQ Version

RabbitMQ currently runs using:

```text
rabbitmq:4.3.4-management
```

The Docker Compose installation is located at:

```text
/opt/rabbitmq
```

The production container is named:

```text
rabbitmq
```

---

## Network Ports

The Docker configuration currently exposes the following relevant ports.

### AMQPS

```text
5671/tcp
```

RabbitMQ listens for encrypted AMQP connections on this port.

The Docker host publishes:

```text
0.0.0.0:5671 -> container:5671
```

This is the production connection used by NAVProxy and other remote DroneNav services.

### Local AMQP

```text
127.0.0.1:5672 -> container:5672
```

Unencrypted AMQP is deliberately restricted to localhost on `lochness`.

It is not exposed publicly.

This port can also be reached through the restricted SSH tunnel described later in this document.

### RabbitMQ Management Interface

```text
127.0.0.1:15672 -> container:15672
```

The RabbitMQ Management HTTP interface is currently restricted to localhost.

It is not publicly exposed.

RabbitMQ also supports a TLS Management API listener on port:

```text
15671
```

The hosting provider has permitted outbound TCP `15671` from `raptor` in case remote access to the Management API is required in the future.

The Management API is **not currently exposed remotely**, so no infrastructure change is required at this time.

---

## Firewall Configuration

### lochness

UFW permits inbound AMQPS traffic from the production application server.

Current production rule:

```text
5671/tcp ALLOW IN <raptor-public-ip>
```

Docker traffic is additionally protected through the `DOCKER-USER` chain.

The policy permits TCP `5671` from the `raptor` public IP and drops other traffic to that port.

Conceptually:

```text
ACCEPT tcp -- <raptor-public-ip>  0.0.0.0/0  tcp dpt:5671
DROP   tcp -- 0.0.0.0/0           0.0.0.0/0  tcp dpt:5671
```

This prevents arbitrary Internet hosts from connecting to the RabbitMQ AMQPS listener even though Docker publishes port `5671`.

### raptor

The hosting provider uses an outbound firewall with an explicit list of permitted destination ports.

The following outbound ports have been enabled:

```text
5671   RabbitMQ AMQPS
15671  RabbitMQ Management API over TLS
```

Port `5671` is required for the production RabbitMQ connection.

Port `15671` is permitted for possible future Management API use but is currently unused.

If a future RabbitMQ connection from `raptor` fails with:

```text
Connection refused
```

and no packets reach `lochness`, verify the hosting provider's outbound firewall configuration before changing RabbitMQ.

---

# TLS Configuration

## Production TLS Files

RabbitMQ uses three TLS files on `lochness`:

```text
/opt/rabbitmq/tls/server_normalized.pem
/opt/rabbitmq/tls/server.key
/opt/rabbitmq/tls/ca_bundle.pem
```

Inside the Docker container these appear as:

```text
/etc/rabbitmq/tls/server_normalized.pem
/etc/rabbitmq/tls/server.key
/etc/rabbitmq/tls/ca_bundle.pem
```

The TLS directory is mounted read-only into the container.

---

## Certificate Roles

### server_normalized.pem

Contains only the leaf/server certificate:

```text
CN = *.dronenav.org
```

The certificate SAN includes:

```text
DNS:*.dronenav.org
DNS:dronenav.org
```

### server.key

Contains the private key corresponding to the wildcard certificate.

The private key must match `server_normalized.pem`.

### ca_bundle.pem

Contains the CA certificates required to construct the server's certificate chain.

For the current certificate issuance this contains:

```text
GlobalSign GCC R6 AlphaSSL CA 2025
GlobalSign Root CA - R6
```

The CA bundle must **not** contain the `*.dronenav.org` leaf certificate.

---

## RabbitMQ TLS Configuration

The production configuration in:

```text
/opt/rabbitmq/rabbitmq.conf
```

contains:

```ini
listeners.ssl.default = 5671

ssl_options.certfile = /etc/rabbitmq/tls/server_normalized.pem
ssl_options.keyfile = /etc/rabbitmq/tls/server.key
ssl_options.cacertfile = /etc/rabbitmq/tls/ca_bundle.pem
ssl_options.verify = verify_none
ssl_options.fail_if_no_peer_cert = false
```

`verify_none` means RabbitMQ does not require clients to present TLS client certificates.

Client authentication is performed using RabbitMQ credentials over the encrypted TLS connection.

---

# Important Certificate Installation Behavior

Do **not** simply point RabbitMQ at the certificate files received from the certificate provider without validating them first.

During the original installation, OpenSSL could successfully parse the provider-supplied leaf certificate, but RabbitMQ/Erlang rejected it during startup with an error equivalent to:

```text
ssl_options.certfile invalid
```

The solution was to normalize the certificate through OpenSSL before installing it.

For example:

```bash
openssl x509 \
  -in STAR_dronenav_org.crt \
  -out server_normalized.pem \
  -outform PEM
```

This creates a clean PEM representation that RabbitMQ/Erlang accepts.

---

# Verify Certificate and Private Key Match

Before installing a renewed certificate, verify that the certificate and private key contain the same public key.

Certificate:

```bash
openssl x509 \
  -in server_normalized.pem \
  -pubkey -noout \
  | openssl sha256
```

Private key:

```bash
openssl pkey \
  -in server.key \
  -pubout \
  | openssl sha256
```

The SHA-256 values must be identical.

Do not install the certificate if they do not match.

---

# Certificate Renewal Procedure

The wildcard certificate expires periodically and must be replaced when the certificate provider reissues it.

Do not assume that the intermediate or root CA certificates will remain unchanged between renewals.

Always use the certificate chain supplied with the new issuance.

## 1. Preserve the Original Issuer Files

Keep the certificate files exactly as received from the issuer.

For the current issuance these were:

```text
STAR_dronenav_org.crt
GlobalSign GCC R6 AlphaSSL CA 2025.crt
RootR6.crt
RootR3.crt
```

These source files should not be modified.

Derived RabbitMQ PEM files can be recreated from them.

---

## 2. Normalize the Leaf Certificate

Create the RabbitMQ leaf certificate:

```bash
openssl x509 \
  -in STAR_dronenav_org.crt \
  -out server_normalized.pem \
  -outform PEM
```

Verify:

```bash
openssl x509 \
  -in server_normalized.pem \
  -noout \
  -subject \
  -issuer \
  -ext subjectAltName
```

The subject/SAN must cover:

```text
rabbitmq.dronenav.org
```

For the wildcard certificate this appears as:

```text
CN=*.dronenav.org
DNS:*.dronenav.org
```

---

## 3. Build the CA Bundle

Normalize the issuer-provided intermediate/root certificates if necessary.

For example:

```bash
openssl x509 \
  -in 'GlobalSign GCC R6 AlphaSSL CA 2025.crt' \
  -out intermediate_normalized.pem \
  -outform PEM
```

Then construct the CA-only bundle using the chain supplied with that year's certificate.

Example:

```bash
{
  cat intermediate_normalized.pem
  printf '\n'
  cat RootR6.crt
  printf '\n'
} > ca_bundle.pem
```

Verify:

```bash
openssl crl2pkcs7 \
  -nocrl \
  -certfile ca_bundle.pem \
  | openssl pkcs7 -print_certs -noout
```

The CA bundle should contain the intermediate/root certificates.

It must **not** contain:

```text
CN=*.dronenav.org
```

---

## 4. Verify Certificate and Key

Verify that the renewed certificate matches the private key.

```bash
openssl x509 \
  -in server_normalized.pem \
  -pubkey -noout \
  | openssl sha256
```

and:

```bash
openssl pkey \
  -in server.key \
  -pubout \
  | openssl sha256
```

The hashes must match.

If the certificate was reissued using a new private key, install the corresponding new `server.key`.

---

## 5. Test Before Updating Production

Never make the first certificate test against the production RabbitMQ container.

Create a temporary RabbitMQ configuration using:

```ini
listeners.ssl.default = 5671

ssl_options.certfile = /etc/rabbitmq/tls/server_normalized.pem
ssl_options.keyfile = /etc/rabbitmq/tls/server.key
ssl_options.cacertfile = /etc/rabbitmq/tls/ca_bundle.pem
ssl_options.verify = verify_none
ssl_options.fail_if_no_peer_cert = false
```

Start a disposable RabbitMQ container using a temporary localhost port such as `5673`.

Example:

```bash
docker run --rm -d \
  --name rabbitmq-cert-test \
  -p 127.0.0.1:5673:5671 \
  -v /path/to/test-rabbitmq.conf:/etc/rabbitmq/rabbitmq.conf:ro \
  -v /opt/rabbitmq/tls:/etc/rabbitmq/tls:ro \
  rabbitmq:4.3.4-management
```

Verify that RabbitMQ starts successfully.

Then inspect the certificate actually presented by RabbitMQ:

```bash
openssl s_client \
  -connect 127.0.0.1:5673 \
  -servername rabbitmq.dronenav.org \
  -showcerts \
  </dev/null
```

The first certificate in the `Certificate chain` section must be:

```text
0 s:CN = *.dronenav.org
```

Do not update the production broker unless this test succeeds.

Remove the disposable container afterward:

```bash
docker rm -f rabbitmq-cert-test
```

---

## 6. Install the Renewed Files

Install the validated files under:

```text
/opt/rabbitmq/tls/
```

The final production directory should contain only the files RabbitMQ requires:

```text
ca_bundle.pem
server.key
server_normalized.pem
```

Example permissions:

```text
-rw-r--r--  root root      ca_bundle.pem
-rw-r-----  root rabbitmq  server.key
-rw-r--r--  root root      server_normalized.pem
```

The exact group ownership of the private key may depend on the Docker/container UID/GID mapping. Verify readability from inside the RabbitMQ container before restarting production.

---

## 7. Restart Production RabbitMQ

From `lochness`:

```bash
cd /opt/rabbitmq
sudo docker compose restart rabbitmq
```

Wait for RabbitMQ to become healthy:

```bash
sudo docker compose ps
```

Expected state:

```text
Up ... (healthy)
```

Verify listeners:

```bash
sudo docker exec rabbitmq rabbitmq-diagnostics listeners
```

The output must include:

```text
port: 5671, protocol: amqp/ssl
```

---

## 8. Verify the Production Certificate

On `lochness`:

```bash
openssl s_client \
  -connect 127.0.0.1:5671 \
  -servername rabbitmq.dronenav.org \
  -showcerts \
  </dev/null
```

Certificate `0` must be:

```text
CN = *.dronenav.org
```

Do not rely solely on the contents of the PEM files.

Always verify the certificate that the running RabbitMQ listener actually presents.

---

## 9. Verify From raptor

Verify the public TLS connection:

```bash
openssl s_client \
  -connect rabbitmq.dronenav.org:5671 \
  -servername rabbitmq.dronenav.org \
  -verify_return_error \
  </dev/null
```

Expected:

```text
Verification: OK
Verify return code: 0 (ok)
```

Finally, test using the actual Python/Pika client environment.

Example:

```python
import ssl
import pika

credentials = pika.PlainCredentials(
    "navproxy",
    "<password>",
)

context = ssl.create_default_context()

parameters = pika.ConnectionParameters(
    host="rabbitmq.dronenav.org",
    port=5671,
    virtual_host="prototype",
    credentials=credentials,
    ssl_options=pika.SSLOptions(
        context,
        "rabbitmq.dronenav.org",
    ),
)

connection = pika.BlockingConnection(parameters)

print("Direct AMQPS connection succeeded")

connection.close()
```

A successful connection confirms all of the following:

```text
DNS
outbound firewall
inbound firewall
Docker port forwarding
RabbitMQ TLS listener
server certificate
certificate chain
hostname validation
RabbitMQ credentials
RabbitMQ virtual host permissions
```

---

# SSH Tunnel Fallback

A restricted SSH key exists between `raptor` and `lochness` for use as a fallback RabbitMQ tunnel.

The tunnel is **not the normal production connection path**.

Normal production traffic uses:

```text
rabbitmq.dronenav.org:5671
```

The SSH tunnel should remain inactive unless required for troubleshooting or emergency access.

The key authorization on `lochness` is deliberately restricted using options such as:

```text
no-agent-forwarding
no-X11-forwarding
no-pty
permitopen="127.0.0.1:5672"
```

This prevents the key from being used as a general-purpose interactive SSH login and restricts forwarding to the local RabbitMQ AMQP listener.

Do not remove this key during normal cleanup. It is retained as an emergency/development fallback.

---

# Troubleshooting

## Connection Refused From raptor

If:

```bash
openssl s_client \
  -connect rabbitmq.dronenav.org:5671 \
  -servername rabbitmq.dronenav.org
```

returns:

```text
Connection refused
```

check:

1. DNS resolution.
2. RabbitMQ container health.
3. RabbitMQ `5671` listener.
4. Docker port publication.
5. UFW rules.
6. `DOCKER-USER` rules.
7. Hosting-provider outbound firewall on `raptor`.

A useful diagnostic on `lochness` is:

```bash
sudo tcpdump -ni any tcp port 5671
```

If the client attempts a connection but **no packets arrive**, investigate the client-side/network-provider path before changing RabbitMQ.

---

## Hostname Mismatch

An error such as:

```text
certificate verify failed:
Hostname mismatch,
certificate is not valid for 'rabbitmq.dronenav.org'
```

means RabbitMQ is presenting the wrong certificate as its server identity.

Check:

```bash
openssl s_client \
  -connect rabbitmq.dronenav.org:5671 \
  -servername rabbitmq.dronenav.org \
  -showcerts \
  </dev/null
```

Certificate `0` must be:

```text
CN = *.dronenav.org
```

---

## Unable to Get Local Issuer Certificate

An error such as:

```text
certificate verify failed:
unable to get local issuer certificate
```

usually means RabbitMQ is presenting the leaf certificate but cannot supply the required intermediate chain.

Verify that:

```ini
ssl_options.certfile
```

points to the normalized leaf certificate and:

```ini
ssl_options.cacertfile
```

points to the CA-only bundle.

---

## RabbitMQ Restart Loop

If:

```bash
sudo docker compose ps
```

shows:

```text
Restarting (1)
```

do not continue changing TLS files.

Inspect:

```bash
sudo docker logs --tail 100 rabbitmq
```

A configuration error such as:

```text
failed_to_prepare_configuration
```

usually indicates that RabbitMQ/Erlang rejected one of the TLS files or configuration values.

Restore the last known working TLS configuration first, return RabbitMQ to a healthy state, and perform further certificate experiments in a disposable container.

---

# Operational Rule

**Never troubleshoot new RabbitMQ certificate material against the production broker first.**

The renewal workflow is:

```text
Receive certificate
        ↓
Preserve issuer originals
        ↓
Normalize leaf certificate
        ↓
Build CA-only bundle
        ↓
Verify certificate/key match
        ↓
Test disposable RabbitMQ container
        ↓
Verify certificate 0 = *.dronenav.org
        ↓
Install production files
        ↓
Restart production RabbitMQ
        ↓
Verify local TLS
        ↓
Verify TLS from raptor
        ↓
Verify Pika connection
```

Following this procedure should make future annual certificate renewals a routine maintenance operation rather than a production troubleshooting exercise.
