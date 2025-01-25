import * as crypto from 'crypto';

import { EufyLogin } from './controllers/Login';
import { MqttConnect } from './controllers/MqttConnect';

export class EufyClean {
    private eufyCleanApi: EufyLogin;
    private openudid: string;

    private username: string;
    private password: string;

    // if the deviceconfig and mqttCredentials are provided the connection will be automatically setup
    constructor(username?: string, password?: string) {
        console.log('EufyClean constructor');

        this.username = username;
        this.password = password;
        this.openudid = crypto.randomBytes(16).toString('hex');
    }

    // Use this method to login and pair new devices.
    public async init(): Promise<any> {
        console.log('EufyClean init');

        this.eufyCleanApi = new EufyLogin(this.username, this.password, this.openudid);

        await this.eufyCleanApi.init();

        return {
            cloudDevices: this.eufyCleanApi.cloudDevices,
            mqttDevices: this.eufyCleanApi.mqttDevices
        };
    }

    public async getCloudDevices() {
        return this.eufyCleanApi.cloudDevices;
    }

    public async getMqttDevices() {
        return this.eufyCleanApi.mqttDevices;
    }

    public async getAllDevices() {
        return [...this.eufyCleanApi.cloudDevices, ...this.eufyCleanApi.mqttDevices]
    }

    public async initDevice(deviceConfig: { deviceId: string, localKey?: string, ip?: string, autoUpdate?: boolean, debug?: boolean }): Promise<MqttConnect | null> {

        // Local connection doesn't require this check
        const devices = await this.getAllDevices();
        const device = devices.find(d => d.deviceId === deviceConfig.deviceId);

        if (!device) {
            return null;
        }

        if (!('localKey' in deviceConfig) && device.mqtt) {
            return new MqttConnect({ ...device, autoUpdate: deviceConfig.autoUpdate, debug: deviceConfig.debug }, this.openudid, this.eufyCleanApi);
        }
    }
}

export * from './constants';
