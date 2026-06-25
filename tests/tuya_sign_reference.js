/**
 * Reference implementation of Tuya Cloud signing from upstream JS.
 * Used to generate known-good signatures for cross-implementation testing.
 *
 * Usage: node tests/tuya_sign_reference.js
 */

const crypto = require('crypto');

// Constants from upstream TuyaCloudApi.ts
const KEY = 'yx5v9uc3ef9wg3v9atje';
const SECRET = 's8x78u7xwymasd9kqa7a73pjhxqsedaj';
const SECRET2 = 'cepev5pfnhua4dkqkdpmnrdxx378mpjr';
const CERT_SIGN = 'A';
const API_ET_VERSION = '0.0.1';

const HMAC_KEY = `${CERT_SIGN}_${SECRET2}_${SECRET}`;

// Fields included in HMAC signature (from upstream TuyaCloud.js)
const VALUES_TO_SIGN = [
  'a', 'v', 'lat', 'lon', 'lang', 'deviceId', 'imei', 'imsi',
  'appVersion', 'ttid', 'isH5', 'h5Token', 'os', 'clientId',
  'postData', 'time', 'requestId', 'n4h5', 'sid', 'sp', 'et',
];

function md5(data) {
  return crypto.createHash('md5').update(data).digest('hex');
}

function mobileHash(data) {
  const preHash = md5(data);
  return preHash.slice(8, 16) + preHash.slice(0, 8) +
         preHash.slice(24, 32) + preHash.slice(16, 24);
}

function hmacSign(key, message) {
  return crypto.createHmac('sha256', key).update(message).digest('hex');
}

function sign(params) {
  const sortedKeys = Object.keys(params).sort();
  let strToSign = '';

  for (const key of sortedKeys) {
    if (!VALUES_TO_SIGN.includes(key) || key === 'sign') {
      continue;
    }
    const value = params[key];
    if (value === null || value === undefined || value === '') {
      continue;
    }

    if (strToSign) {
      strToSign += '||';
    }

    if (key === 'postData') {
      strToSign += key + '=' + mobileHash(String(value));
    } else {
      strToSign += key + '=' + value;
    }
  }

  return {
    signString: strToSign,
    signature: hmacSign(HMAC_KEY, strToSign),
  };
}

// Test Case 1: Simple request without postData (like token.create first step check)
const testCase1 = {
  a: 'tuya.m.user.uid.token.create',
  deviceId: 'abc123def456abc123def456abc123de',
  sdkVersion: '3.0.0cAnker',
  os: 'Android',
  lang: 'en',
  appVersion: '3.8.5',
  v: '1.0',
  clientId: KEY,
  time: 1700000000,
  et: API_ET_VERSION,
  ttid: 'android',
  appRnVersion: '5.11',
  platform: 'Android',
  requestId: '12345678-1234-1234-1234-123456789abc',
  postData: JSON.stringify({ countryCode: 'EU', uid: 'eh-testuser123' }),
};

// Test Case 2: Request with postData but no sid
const testCase2 = {
  a: 'tuya.m.user.uid.password.login',
  deviceId: 'abc123def456abc123def456abc123de',
  sdkVersion: '3.0.0cAnker',
  os: 'Android',
  lang: 'en',
  appVersion: '3.8.5',
  v: '1.0',
  clientId: KEY,
  time: 1700000000,
  et: API_ET_VERSION,
  ttid: 'android',
  appRnVersion: '5.11',
  platform: 'Android',
  requestId: '12345678-1234-1234-1234-123456789abc',
  postData: JSON.stringify({
    countryCode: 'EU',
    uid: 'eh-testuser123',
    createGroup: true,
    passwd: 'encryptedpassword',
    ifencrypt: 1,
    options: { group: 1 },
    token: 'sometoken',
  }),
};

// Test Case 3: Request with sid (authenticated)
const testCase3 = {
  a: 'tuya.m.location.list',
  deviceId: 'abc123def456abc123def456abc123de',
  sdkVersion: '3.0.0cAnker',
  os: 'Android',
  lang: 'en',
  appVersion: '3.8.5',
  v: '1.0',
  clientId: KEY,
  time: 1700000000,
  et: API_ET_VERSION,
  ttid: 'android',
  appRnVersion: '5.11',
  platform: 'Android',
  requestId: '12345678-1234-1234-1234-123456789abc',
  sid: 'test-session-id-12345',
};

// Output results as JSON for Python test to consume
const results = {
  hmac_key: HMAC_KEY,
  test_cases: [
    {
      name: 'token_create_with_postdata',
      params: testCase1,
      postData_raw: testCase1.postData,
      postData_mobile_hash: mobileHash(testCase1.postData),
      ...sign(testCase1),
    },
    {
      name: 'password_login_with_postdata',
      params: testCase2,
      postData_raw: testCase2.postData,
      postData_mobile_hash: mobileHash(testCase2.postData),
      ...sign(testCase2),
    },
    {
      name: 'authenticated_request_no_postdata',
      params: testCase3,
      ...sign(testCase3),
    },
  ],
};

console.log(JSON.stringify(results, null, 2));
