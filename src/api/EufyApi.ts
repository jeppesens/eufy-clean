import axios, { AxiosInstance } from 'axios';
import * as crypto from 'crypto';


export class EufyApi {
    private requestClient: AxiosInstance;
    private username: string;
    private password: string;
    public openudid: string;
    public session: any;
    public userInfo: any;

    constructor(username: string, password: string, openudid: string) {
        this.username = username;
        this.password = password;
        this.openudid = openudid;

        this.requestClient = axios.create();
    }

    public async login(): Promise<any> {
        const session = await this.eufyLogin();
        const user = await this.getUserinfo();
        const mqtt = await this.getMqttCredentials();

        return { session, user, mqtt };
    }

    public async sofLogin(): Promise<any> {
        const session = await this.eufyLogin();

        return { session };
    }

    public async eufyLogin(): Promise<void> {
        return await this.requestClient({
            method: 'post',
            url: 'https://home-api.eufylife.com/v1/user/email/login',
            headers: {
                category: 'Home',
                Accept: '*/*',
                openudid: this.openudid,
                'Content-Type': 'application/json',
                clientType: '1',
                'User-Agent': 'EufyHome-iOS-2.14.0-6',
                Connection: 'keep-alive',
            },
            data: {
                email: this.username,
                password: this.password,
                client_id: 'eufyhome-app',
                client_secret: 'GQCpr9dSp3uQpsOMgJ4xQ',
            },
        })
            .then((res) => {
                if (res.data && res.data.access_token) {
                    console.info('eufyLogin successful');

                    this.session = res.data;

                    return res.data;
                } else {
                    console.error('Login failed: ' + JSON.stringify(res.data));
                    return;
                }
            })
            .catch((error) => {
                console.error(error);
                console.error('Login failed');
                error.response && console.error(JSON.stringify(error.response.data));
            });
    }

    public async getUserinfo(): Promise<void> {
        return await this.requestClient({
            method: 'get',
            maxBodyLength: Infinity,
            url: 'https://api.eufylife.com/v1/user/user_center_info',
            headers: {
                'content-type': 'application/x-www-form-urlencoded; charset=UTF-8',
                'user-agent': 'EufyHome-Android-3.1.3-753',
                category: 'Home',
                token: this.session.access_token,
                openudid: this.openudid,
                clienttype: '2',
            },
        })
            .then(async (res) => {
                this.userInfo = res.data;
                //md5 hash of userid
                if (!res.data.user_center_id) {
                    console.error('No user_center_id found');
                    return;
                }
                this.userInfo.gtoken = crypto.createHash('md5').update(res.data.user_center_id).digest('hex');
            })
            .catch((error) => {
                console.error('get user center info failed');
                console.error(error);
                error.response && console.error(JSON.stringify(error.response.data));
            });
    }

    public async getCloudDeviceList(): Promise<string[]> {
        //get general device list
        const devices = await this.requestClient({
            method: 'get',
            maxBodyLength: Infinity,
            url: 'https://api.eufylife.com/v1/device/v2',
            headers: {
                'content-type': 'application/x-www-form-urlencoded; charset=UTF-8',
                'user-agent': 'EufyHome-Android-3.1.3-753',
                category: 'Home',
                token: this.session.access_token,
                openudid: this.openudid,
                clienttype: '2',
            },
        })
            .then(async (res) => {
                let data = res.data;

                if (res.data.data) {
                    data = res.data.data;
                }

                console.info(`Found ${data.devices.length} devices via Eufy Cloud`);
                return data.devices;
            })
            .catch((error) => {
                console.error('get device list failed');
                console.error(error);
                error.response && console.error(JSON.stringify(error.response.data));
            });

        return devices;
    }

    public async getDeviceList(device_sn?: string): Promise<any> {
        const devices = await this.requestClient({
            method: 'post',
            maxBodyLength: Infinity,
            url: 'https://aiot-clean-api-pr.eufylife.com/app/devicerelation/get_device_list',
            headers: {
                'user-agent': 'EufyHome-Android-3.1.3-753',
                openudid: this.openudid,
                'os-version': 'Android',
                'model-type': 'PHONE',
                'app-name': 'eufy_home',
                'x-auth-token': this.userInfo.user_center_token,
                gtoken: this.userInfo.gtoken,
                'content-type': 'application/json; charset=UTF-8',
            },
            data: { attribute: 3 },
        })
            .then(async (res) => {

                const deviceArray = [];

                let data = res.data;

                if (res.data.data) {
                    data = res.data.data;
                }

                if (data.devices) {
                    for (const deviceObject of data.devices) {
                        deviceArray.push(deviceObject.device);
                    }

                    if (device_sn?.length) {
                        return deviceArray.find((device: any) => device.device_sn === device_sn);
                    }
                }

                console.info(`Found ${deviceArray.length} devices via Eufy MQTT`);

                return deviceArray;
            })
            .catch((error) => {
                console.error('update device failed');
                console.error(error);
                error.response && console.error(JSON.stringify(error.response.data));
            });

        return devices;
    }


    async getDeviceProperties(deviceModel: string): Promise<void> {
        const base64 = [];
        const base64ToHex = [];
        await this.requestClient({
            method: 'post',
            maxBodyLength: Infinity,
            url: 'https://aiot-clean-api-pr.eufylife.com/app/things/get_product_data_point',
            headers: {
                'user-agent': 'EufyHome-Android-3.1.3-753',
                openudid: this.openudid,
                'os-version': 'Android',
                'model-type': 'PHONE',
                'app-name': 'eufy_home',
                'x-auth-token': this.userInfo.user_center_token,
                gtoken: this.userInfo.gtoken,
                'content-type': 'application/json; charset=UTF-8',
            },
            data: { code: deviceModel },
        })
            .then(async (res) => {
                console.debug(JSON.stringify(res.data, null, 2));
                // if (res.data.data && res.data.data.data_point_list) {
                //   this.dataPoints[currentModel] = res.data.data.data_point_list;
                //   for (const dataPoint of res.data.data.data_point_list) {
                //     this.descriptions[dataPoint.dp_id] = dataPoint.code;
                //     if (dataPoint.data_type === 'String') {
                //       base64.push(dataPoint.dp_id);
                //     }
                //     if (dataPoint.data_type === 'Raw') {
                //       base64ToHex.push(dataPoint.dp_id.toString());
                //     }
                //   }
                // }
            })

            .catch((error) => {
                console.error('get product data point failed');
                console.error(error);
                error.response && console.error(JSON.stringify(error.response.data));
            });
    }


    public async getMqttCredentials(): Promise<void> {
        return await this.requestClient({
            method: 'post',
            maxBodyLength: Infinity,
            url: 'https://aiot-clean-api-pr.eufylife.com/app/devicemanage/get_user_mqtt_info',
            headers: {
                'content-type': 'application/json',
                'user-agent': 'EufyHome-Android-3.1.3-753',
                openudid: this.openudid,
                'os-version': 'Android',
                'model-type': 'PHONE',
                'app-name': 'eufy_home',
                'x-auth-token': this.userInfo.user_center_token,
                gtoken: this.userInfo.gtoken,
            },
        })
            .then(async (res) => {
                return res.data.data;
            })
            .catch((error) => {
                console.error('get mqtt failed');
                console.error(error);
                error.response && console.error(JSON.stringify(error.response.data));
            });
    }
}
