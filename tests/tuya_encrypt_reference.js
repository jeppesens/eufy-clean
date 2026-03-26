/**
 * Reference implementation of Tuya Cloud password encryption from upstream JS.
 * Replicates the loginEx flow from martijnpoppen/eufy-clean TuyaCloud.js.
 *
 * Usage: node tests/tuya_encrypt_reference.js
 */

const crypto = require('crypto');

// AES key/iv (hardcoded in upstream TuyaCloud.js)
const AES_KEY = Buffer.from([36, 78, 109, 138, 86, 172, 135, 145, 36, 67, 45, 139, 108, 188, 162, 196]);
const AES_IV = Buffer.from([119, 36, 86, 242, 167, 102, 76, 243, 57, 44, 53, 151, 233, 62, 87, 71]);

function md5(data) {
  return crypto.createHash('md5').update(data).digest('hex');
}

/**
 * Encrypt password for Tuya loginEx (exact upstream logic from TuyaCloud.js).
 * Returns intermediate values for debugging.
 */
function encryptPassword(uid, publicKeyN, exponent) {
  // Step 1: Pad uid to 16-byte boundary (left-pad with zeros)
  const fullUid = 'eh-' + uid;
  const paddingSize = 16 * Math.ceil(fullUid.length / 16);
  const filledUid = fullUid.padStart(paddingSize, '0');

  // Step 2: AES-128-CBC encrypt (upstream only calls cipher.update, NOT cipher.final)
  const cipher = crypto.createCipheriv('aes-128-cbc', AES_KEY, AES_IV);
  const encrypted = cipher.update(filledUid, 'utf8', 'hex');
  // NOTE: upstream does NOT call cipher.final() !

  // Step 3: MD5 of uppercase hex
  const encryptedUpper = encrypted.toUpperCase();
  const passwordMd5 = md5(encryptedUpper);

  // Step 4: RSA encrypt (raw textbook RSA: m^e mod n)
  const n = BigInt('0x' + publicKeyN);
  const e = BigInt(exponent);
  const m = BigInt('0x' + Buffer.from(passwordMd5).toString('hex'));
  const c = modPow(m, e, n);

  // Convert to hex, zero-padded to key size
  const keySize = Math.ceil(publicKeyN.length / 2);
  const rsaHex = c.toString(16).padStart(keySize * 2, '0');

  return {
    fullUid,
    paddingSize,
    filledUid,
    aesHex: encrypted,
    aesHexUpper: encryptedUpper,
    passwordMd5,
    rsaHex,
  };
}

/**
 * Also test what happens when cipher.final() IS called (Python behavior).
 */
function encryptPasswordWithFinal(uid, publicKeyN, exponent) {
  const fullUid = 'eh-' + uid;
  const paddingSize = 16 * Math.ceil(fullUid.length / 16);
  const filledUid = fullUid.padStart(paddingSize, '0');

  const cipher = crypto.createCipheriv('aes-128-cbc', AES_KEY, AES_IV);
  const encrypted = cipher.update(filledUid, 'utf8', 'hex') + cipher.final('hex');
  // ^ WITH cipher.final() - adds PKCS7 padding

  const encryptedUpper = encrypted.toUpperCase();
  const passwordMd5 = md5(encryptedUpper);

  return {
    aesHexWithFinal: encrypted,
    aesHexUpperWithFinal: encryptedUpper,
    passwordMd5WithFinal: passwordMd5,
  };
}

function modPow(base, exp, mod) {
  let result = 1n;
  base = base % mod;
  while (exp > 0n) {
    if (exp % 2n === 1n) {
      result = (result * base) % mod;
    }
    exp = exp / 2n;
    base = (base * base) % mod;
  }
  return result;
}

// Test with a known RSA key pair (small for testing)
const testPublicKeyN = '00b3510a2e6c4fa1e339a0703e64444c0c4a0663385dbd0d2c2c0a8e2b4f1c63';
const testExponent = 65537;

// Test Case 1: Short uid
const case1 = encryptPassword('testuser123', testPublicKeyN, testExponent);
const case1WithFinal = encryptPasswordWithFinal('testuser123', testPublicKeyN, testExponent);

// Test Case 2: Longer uid (crosses 16-byte boundary)
const case2 = encryptPassword('a1b2c3d4e5f6g7h8i9j0k1l2m3', testPublicKeyN, testExponent);
const case2WithFinal = encryptPasswordWithFinal('a1b2c3d4e5f6g7h8i9j0k1l2m3', testPublicKeyN, testExponent);

const results = {
  aes_key_hex: AES_KEY.toString('hex'),
  aes_iv_hex: AES_IV.toString('hex'),
  test_cases: [
    {
      name: 'short_uid',
      uid: 'testuser123',
      ...case1,
      ...case1WithFinal,
    },
    {
      name: 'long_uid',
      uid: 'a1b2c3d4e5f6g7h8i9j0k1l2m3',
      ...case2,
      ...case2WithFinal,
    },
  ],
};

console.log(JSON.stringify(results, null, 2));
