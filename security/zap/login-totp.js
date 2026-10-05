// ZAP authentication script (E09-X03): password + TOTP, re-run by ZAP whenever the
// logged-in indicator is lost (session rotation, SR-013). Secrets come from env only.
// Endpoints follow docs/plan/22-api-openapi.yaml: POST /v1/auth/login -> mfa_token,
// POST /v1/auth/mfa/verify -> session cookie.
var HttpRequestHeader = Java.type("org.parosproxy.paros.network.HttpRequestHeader");
var HttpHeader = Java.type("org.parosproxy.paros.network.HttpHeader");
var HttpMessage = Java.type("org.parosproxy.paros.network.HttpMessage");
var URI = Java.type("org.apache.commons.httpclient.URI");
var System = Java.type("java.lang.System");

function totp(secretBase32) {
  var B32 = "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567", bits = "", i;
  for (i = 0; i < secretBase32.length; i++) {
    bits += ("00000" + B32.indexOf(secretBase32.charAt(i).toUpperCase()).toString(2)).slice(-5);
  }
  var key = [];
  for (i = 0; i + 8 <= bits.length; i += 8) key.push(parseInt(bits.substr(i, 8), 2) << 24 >> 24);
  var counter = Math.floor(Date.now() / 30000), msg = [];
  for (i = 7; i >= 0; i--) { msg[i] = counter & 0xff; counter = Math.floor(counter / 256); }
  var Mac = Java.type("javax.crypto.Mac"), Spec = Java.type("javax.crypto.spec.SecretKeySpec");
  var mac = Mac.getInstance("HmacSHA1");
  mac.init(new Spec(Java.to(key, "byte[]"), "HmacSHA1"));
  var h = mac.doFinal(Java.to(msg, "byte[]"));
  var o = h[19] & 0xf;
  var code = (((h[o] & 0x7f) << 24) | ((h[o + 1] & 0xff) << 16) | ((h[o + 2] & 0xff) << 8) | (h[o + 3] & 0xff)) % 1000000;
  return ("000000" + code).slice(-6);
}

function post(helper, url, body) {
  var msg = new HttpMessage(new URI(url, false), "POST", "HTTP/1.1");
  msg.getRequestHeader().setHeader(HttpHeader.CONTENT_TYPE, "application/json");
  msg.setRequestBody(body);
  msg.getRequestHeader().setContentLength(msg.getRequestBody().length());
  helper.sendAndReceive(msg, false);
  return msg;
}

function authenticate(helper, paramsValues, credentials) {
  var target = System.getenv("ZAP_TARGET");
  var login = post(helper, target + "/v1/auth/login", JSON.stringify({
    identifier: credentials.getParam("username"), password: credentials.getParam("password")
  }));
  var body = JSON.parse(login.getResponseBody().toString());
  // Testnet fixture owner seeded with --allow-no-mfa (EX-01): login issues the session directly.
  if (!body.mfa_token) { return login; }
  var mfaToken = body.mfa_token;
  return post(helper, target + "/v1/auth/mfa/verify", JSON.stringify({
    mfa_token: mfaToken, code: totp(credentials.getParam("totpSecret"))
  }));
}

function getRequiredParamsNames() { return []; }
function getOptionalParamsNames() { return []; }
function getCredentialsParamsNames() { return ["username", "password", "totpSecret"]; }
