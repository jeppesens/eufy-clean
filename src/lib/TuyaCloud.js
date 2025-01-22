// @ts-nocheck
const crypto = require('crypto');
const is = require('is');
const got = require('got');
const randomize = require('randomatic');
const sortObject = require('sort-keys-recursive');
const NodeRSA = require('node-rsa');
const { v4: uuidv4 } = require('uuid');
// Error object
class TuyaCloudRequestError extends Error {
  constructor(options) {
    super();
    this.code = options.code;
    this.message = options.message;
  }
}

/**
 * A TuyaCloud object.
 * Providing `apiEtVersion` option means that the new sign mechanism (HMAC-SHA256)
 * instead of old (MD5) will be used. This also makes `secret2` and `certSign` mandatory.
 * @class
 * @param {Object} options construction options
 * @param {String} options.key API key
 * @param {String} options.secret API secret
 * @param {String} [options.apiEtVersion]
 * Tag existing in new mobile api version (as const '0.0.1'),
 * @param {String} [options.secret2]
 * Second API secret token, stored in BMP file (mandatory if apiEtVersion is specified)
 * @param {String} [options.certSign]
 * App certificate SHA256 (mandatory if apiEtVersion is specified)
 * @param {String} [options.region='AZ'] region (AZ=Americas, AY=Asia, EU=Europe, IN=India) - or a region saved earlier
 * @param {String} [options.endpoint] endpoint stored after a former loginEx call (mostly together with sid and region)
 * @param {String} [options.deviceID] ID of device calling API (defaults to a random value)
 * @param {String} [options.ttid] app id (defaults to 'tuya'), alternative is "smart_life" depending on used App
 * @param {String} [options.sid] session id if obtained in the past to reuse (optional)
 * @example <caption>Using the MD5 signing mechanism:</caption>
 * const api = new Cloud({key: 'your-api-key', secret: 'your-api-secret'})
 * @example <caption>Using the HMAC-SHA256 signing mechanism:</caption>
 * const api = new Cloud({key: 'your-api-key', secret: 'your-api-secret',
 *                        apiEtVersion: '0.0.1', secret2: 'your-apm-secret2',
 *                        certSign: 'your-api-cert-sign'})
 */
function TuyaCloud(options) {
  // Set to empty object if undefined
  options = is.undefined(options) ? {} : options;

  // Key and secret
  if (!options.key || !options.secret || options.key.length !== 20 || options.secret.length !== 32) {
    throw new Error('Invalid format for key or secret.');
  } else {
    this.key = options.key;
    this.secret = options.secret;
  }

  // New API: check mandatory params
  if (options.apiEtVersion) {
    // console.debug('using new API');

    this.keyHmac = options.certSign + '_' + options.secret2 + '_' + options.secret;
    this.apiEtVersion = options.apiEtVersion;
    this.ttid = options.ttid || 'tuya';
    // console.debug('key HMAC: ' + this.keyHmac);
  }

  // Device ID
  if (is.undefined(options.deviceID)) {
    this.deviceID = randomize('a0', 44, options);
  } else {
    this.deviceID = options.deviceID;
  }

  // Endpoint
  if (!is.undefined(options.endpoint) && !is.undefined(options.region)) {
    this.endpoint = options.endpoint;
    this.region = options.region;
  }
  // Region
  else if (is.undefined(options.region) || options.region === 'AZ') {
    this.region = 'AZ';
    this.endpoint = 'https://a1.tuyaus.com/api.json';
  } else if (options.region === 'US') {
    this.region = 'AZ';
    this.endpoint = 'https://a1.tuyaus.com/api.json';
  } else if (options.region === 'AY') {
    this.region = 'AY';
    this.endpoint = 'https://a1.tuyacn.com/api.json';
  } else if (options.region === 'EU') {
    this.region = 'EU';
    this.endpoint = 'https://a1.tuyaeu.com/api.json';
  } else if (options.region === 'IN') {
    this.region = 'IN';
    this.endpoint = 'https://a1.tuyain.com/api.json';
  } else {
    throw new Error('Bad region identifier.');
  }

  // Session ID
  if (!is.undefined(options.sid)) {
    this.sid = options.sid;
  }
}

/**
 * Slices and dices an MD5 digest
 * to conform to Tuya's spec.
 * Don't ask why this is needed.
 * @param {String} data to hash
 * @returns {String} resulting digest
 * @private
 */
TuyaCloud.prototype._mobileHash = function (data) {
  const preHash = md5(data);

  return preHash.slice(8, 16) + preHash.slice(0, 8) + preHash.slice(24, 32) + preHash.slice(16, 24);
};

/**
 * Sends an API request
 * @param {Object} options
 * request options
 * @param {String} options.action
 * API action to invoke (for example, 'tuya.cloud.device.token.create')
 * @param {Object} [options.data={}]
 * data to send in the request body
 * @param {String} [options.deviceID=undefined]
 * DEvice ID param
 * @param {String} [options.gid]
 * Group ID URL GET param (necessary for device-related actions)
 * @param {String} [options.version='1.0']
 * API version to use for the request (some IR related calls require '5.0' as version)
 * @param {Boolean} [options.requiresSID=true]
 * set to false if the request doesn't require a session ID
 * @example
 * // generate a new token
 * api.request({action: 'tuya.m.device.token.create',
 *              data: {'timeZone': '-05:00'}}).then(token => console.log(token))
 * @returns {Promise<Object>} A Promise that contains the response body parsed as JSON
 */
TuyaCloud.prototype.request = async function (options) {
  // Set to empty object if undefined
  options = is.undefined(options) ? {} : options;

  // Check arguments
  if (is.undefined(options.requiresSID)) {
    options.requiresSID = true;
  }

  if (!options.action) {
    throw new Error('Must specify an action to call.');
  }

  // Must have SID if we need it later
  if (!this.sid && options.requiresSID) {
    throw new Error('Must call login() first.');
  }

  const d = new Date();
  const pairs = {
    a: options.action,
    deviceId: this.deviceID,
    sdkVersion: '3.0.0cAnker',
    os: 'Android',
    lang: 'en',
    appVersion: '2.3.2',
    v: options.version || '1.0',
    clientId: this.key,
    time: Math.round(d.getTime() / 1000),
  };

  if (options.data) {
    pairs.postData = JSON.stringify(options.data);
  }
  if (options.gid) {
    pairs.gid = options.gid;
  }

  if (this.apiEtVersion) {
    pairs.et = this.apiEtVersion;
    pairs.ttid = this.ttid;
    pairs.appVersion = '3.8.5';
    pairs.appRnVersion = '5.11';
    pairs.platform = 'Android';
    pairs.requestId = uuidv4();
  }

  if (options.requiresSID) {
    pairs.sid = this.sid;
  }

  // Generate signature for request
  const valuesToSign = [
    'a',
    'v',
    'lat',
    'lon',
    'lang',
    'deviceId',
    'imei',
    'imsi',
    'appVersion',
    'ttid',
    'isH5',
    'h5Token',
    'os',
    'clientId',
    'postData',
    'time',
    'requestId',
    'n4h5',
    'sid',
    'sp',
    'et',
  ];

  const sortedPairs = sortObject(pairs);

  let strToSign = '';

  // Create string to sign
  for (const key in sortedPairs) {
    if (!valuesToSign.includes(key) || is.empty(pairs[key])) {
      continue;
    } else if (key === 'postData') {
      if (strToSign) {
        strToSign += '||';
      }
      strToSign += key;
      strToSign += '=';
      strToSign += this._mobileHash(pairs[key]);
    } else {
      if (strToSign) {
        strToSign += '||';
      }
      strToSign += key;
      strToSign += '=';
      strToSign += pairs[key];
    }
  }

  if (this.apiEtVersion) {
    // New API, use HMAC-SHA256
    // console.debug('strToSign: ' + strToSign);
    pairs.sign = crypto.createHmac('sha256', this.keyHmac).update(strToSign).digest('hex');
  } else {
    // Add secret
    strToSign += '||';
    strToSign += this.secret;
    // console.debug('strToSign: ' + strToSign);

    // Sign string
    pairs.sign = md5(strToSign);
  }

//   console.debug('Sending parameters:');
//   console.debug(JSON.stringify(pairs));

  const apiResult = await got(this.endpoint, {
    searchParams: pairs,
    timeout: {
      request: 10000,
    },
  }).catch((err) => {
    console.error('Error sending request: ' + err);
  });
  const data = JSON.parse(apiResult.body);

//   console.debug('Received response:');
//   console.debug(apiResult.body);

  if (data.success === false) {
    throw new TuyaCloudRequestError({ code: data.errorCode, message: data.errorMsg });
  }

  return data.result;
};

/**
* Helper to register a new user. If user already exists, it instead attempts to log in.
* @param {Object} options
* register options
* @param {String} options.email
* email to register
* @param {String} options.password
* password for new user
* @example
* api.register({email: 'example@example.com',
                password: 'example-password'})
                .then(sid => console.log('Session ID: ', sid))
* @returns {Promise<String>} A Promise that contains the session ID
*/
TuyaCloud.prototype.register = async function (options) {
  try {
    const apiResult = await this.request({
      action: 'tuya.m.user.email.register',
      data: { countryCode: this.region, email: options.email, passwd: md5(options.password) },
      requiresSID: false,
    });

    this.sid = apiResult.sid;
    return this.sid;
  } catch (err) {
    if (err.code === 'USER_NAME_IS_EXIST') {
      return this.login(options);
    }

    throw err;
  }
};

/**
* Helper to log in a user.
* @param {Object} options
* register options
* @param {String} options.email
* user's email
* @param {String} options.password
* user's password
* @param {String} options.returnFullLoginResponse
* true to return the full login response, false to return just the session ID* @example
* api.login({email: 'example@example.com',
             password: 'example-password'}).then(sid => console.log('Session ID: ', sid))
* @returns {Promise<String|Object>} A Promise that contains the session ID
*/
TuyaCloud.prototype.login = async function (options) {
  const apiResult = await this.request({
    action: 'tuya.m.user.email.password.login',
    data: { countryCode: this.region, email: options.email, passwd: md5(options.password) },
    requiresSID: false,
  });
  this.sid = apiResult.sid;
  if (is.boolean(options.returnFullLoginResponse) && options.returnFullLoginResponse) {
    return apiResult;
  }
  return this.sid;
};

/**
* Helper to log in a user using enhanced login process (using empheral asymmetric RSA key)
* @param {Object} options
* register options
* @param {String} options.email
* user's email
* @param {String} options.password
* @param {String} options.uid
* user's password
* @param {String} options.returnFullLoginResponse
* true to return the full login response, false to return just the session ID
* api.loginEx({email: 'example@example.com',
            password: 'example-password'}).then(sid => console.log('Session ID: ', sid))
* @returns {Promise<String|Object>} A Promise that contains the session ID
*/
TuyaCloud.prototype.loginEx = async function (options) {
  // Get token and empheral RSA public key
  const token = await this.request({
    action: 'tuya.m.user.uid.token.create',
    data: {  countryCode: this.region, uid: 'eh-' + options.uid },
    requiresSID: false,
  });

  // Create RSA public key: match the settings from mobile app (no padding)

  const key = new NodeRSA(
    {},
    {
      encryptionScheme: {
        scheme: 'pkcs1',
        padding: crypto.constants.RSA_NO_PADDING,
      },
    },
  );

  key.importKey(
    {
      n: token.publicKey,
      e: Number(token.exponent),
    },
    'components-public',
  );

  const cipher = crypto.createCipheriv(
    'aes-128-cbc',
    Buffer.from([36, 78, 109, 138, 86, 172, 135, 145, 36, 67, 45, 139, 108, 188, 162, 196]),
    Buffer.from([119, 36, 86, 242, 167, 102, 76, 243, 57, 44, 53, 151, 233, 62, 87, 71]),
  );
  const paddingSize = 16 * Math.ceil(('eh-' + options.uid).length / 16);
  const filleduid = ('eh-' + options.uid).padStart(paddingSize, '0');
  const encrypted = cipher.update(filleduid, 'utf8', 'hex');

  const encryptedPass = key.encrypt(Buffer.from(md5(encrypted.toUpperCase())), 'hex');

  const apiResult = await this.request({
    action: 'tuya.m.user.uid.password.login',
    data: {
      countryCode: this.region,
      uid: 'eh-' + options.uid,
      createGroup: true,
      passwd: encryptedPass,
      ifencrypt: 1,
      options: { group: 1 },
      token: token.token,
    },
    requiresSID: false,
  });

  // Change endpoint if necessary
  // (the SID will only be vaild in endpoint given in response)
  if (apiResult.domain.mobileApiUrl && !this.endpoint.startsWith(apiResult.domain.mobileApiUrl)) {
    // console.debug(
    //   'Changing endpoints after logging: %s -> %s/api.json',
    //   this.endpoint,
    //   apiResult.domain.mobileApiUrl,
    // );

    this.endpoint = apiResult.domain.mobileApiUrl + '/api.json';
    this.region = apiResult.domain.regionCode;
  }

  this.sid = apiResult.sid;
  if (is.boolean(options.returnFullLoginResponse) && options.returnFullLoginResponse) {
    return apiResult;
  }
  return this.sid;
};

/**
 * Helper to wait for device(s) to be registered.
 * It's possible to register multiple devices at once,
 * so this returns an array.
 * @param {Object} options
 * options
 * @param {String} options.token
 * token being registered
 * @param {Number} [options.devices=1]
 * number of devices to wait for
 * @example
 * api.waitForToken({token: token.token}).then(result => {
 *   let device = result[0];
 *   console.log('Params:');
 *   console.log(JSON.stringify({id: device['id'], localKey: device['localKey']}));
 * });
 * @returns {Promise<Array>} A Promise that contains an array of registered devices
 */
TuyaCloud.prototype.waitForToken = function (options) {
  if (!options.devices) {
    options.devices = 1;
  }

  // eslint-disable-next-line no-async-promise-executor
  return new Promise(async (resolve, reject) => {
    for (let i = 0; i < 200; i++) {
      try {
        /* eslint-disable-next-line no-await-in-loop */
        const tokenResult = await this.request({ action: 'tuya.m.device.list.token', data: { token: options.token } });

        if (tokenResult.length >= options.devices) {
          return resolve(tokenResult);
        }

        // Wait for 200 ms
        /* eslint-disable-next-line no-await-in-loop */
        await delay(200);
      } catch (err) {
        reject(err);
      }
    }
    reject(new Error('Timed out waiting for device(s) to connect to cloud'));
  });
};

function delay(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}
function md5(data) {
  return crypto.createHash('md5').update(data).digest('hex');
}
module.exports = TuyaCloud;
