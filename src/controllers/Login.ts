import { EufyApi } from '../api/EufyApi';
import { TuyaCloudApi } from '../api/TuyaCloudApi';
import { Base } from './Base';

export class EufyLogin extends Base {
    private tuyaApi: TuyaCloudApi | null = null;
    private eufyApi: EufyApi;

    private username: string;
    private password: string;

    private sid: string;
    public mqttCredentials: any;

    public cloudDevices: any[] = [];
    public mqttDevices: any[] = [];
    public eufyApiDevices: any[] = [];

    constructor(username: string, password: string, openudid: string) {
        super();

        this.username = username;
        this.password = password;
        this.eufyApi = new EufyApi(username, password, openudid);
    }

    public async init(): Promise<void> {
        await this.login({ mqtt: true, tuya: true });
        return await this.getDevices();
    }

    public async login(config: { mqtt: boolean, tuya: boolean }): Promise<void> {
        let eufyLogin = null;

        if (config.mqtt) {
            eufyLogin = await this.eufyApi.login();
        } else {
            eufyLogin = await this.eufyApi.sofLogin();
        }

        if (eufyLogin) {
            if (config.mqtt) {
                this.mqttCredentials = eufyLogin.mqtt;
            }

            if (config.tuya) {
                try {
                    this.tuyaApi = new TuyaCloudApi(this.username, this.password, eufyLogin.session.user_id, 'EU');
                    this.sid = await this.tuyaApi.login();
                    console.log('TuyaCloudApi EU login successful');
                } catch (error) {
                    console.error('TuyaCloudApi EU login failed');
                    console.error(error)

                    try {
                        this.tuyaApi = new TuyaCloudApi(this.username, this.password, eufyLogin.session.user_id, 'US');
                        this.sid = await this.tuyaApi.login();
                        console.log('TuyaCloudApi US login successful');
                    } catch (error) {
                        console.error('TuyaCloudApi US login failed');
                        console.error(error)
                    }
                }
            }
        }
    }

    public async checkLogin(): Promise<void> {
        if (!this.sid) {
            await this.login({ mqtt: true, tuya: true });
        }
    }

    public async getDevices(): Promise<any> {
        // // Get all devices from the Eufy Cloud API.
        this.eufyApiDevices = await this.eufyApi.getCloudDeviceList();

        if (this.sid) {
            this.cloudDevices = await this.tuyaApi.getDeviceList();
            this.cloudDevices = this.cloudDevices.map(device => ({
                ...this.findModel(device.devId),
                apiType: this.checkApiType(device.dps),
                mqtt: false,
                dps: device?.dps || {}
            }));
        }

        // Devices like the X10 are not supported by the Tuya Cloud API
        this.mqttDevices = await this.eufyApi.getDeviceList();
        this.mqttDevices = this.mqttDevices.map(device => ({
            ...this.findModel(device.device_sn),
            apiType: this.checkApiType(device.dps),
            mqtt: true,
            dps: device?.dps || {}
        }));

        this.mqttDevices = this.mqttDevices.filter(device => !device.invalid);
    }

    public async getCloudDevice(deviceId: string): Promise<any> {
        try {
            await this.checkLogin();
            return await this.tuyaApi.getDevice(deviceId);
        } catch (error) {
            this.sid = null;
            throw new Error(error);

        }
    }

    public async sendCloudCommand(deviceId: string, dps: any): Promise<any> {
        try {
            await this.checkLogin();
            return await this.tuyaApi.sendCommand(deviceId, dps);
        } catch (error) {
            this.sid = null;
            throw new Error(error);
        }
    }

    public async getMqttDevice(deviceId: string): Promise<any> {
        return await this.eufyApi.getDeviceList(deviceId);
    }

    private checkApiType(dps) {
        if (Object.values(this.novelDPSMap).some(k => k in dps)) {
            return 'novel'
        }

        return 'legacy'
    }

    private findModel(deviceId: string) {
        const device = this.eufyApiDevices.find(d => d.id === deviceId);

        if (device) {
            return {
                deviceId,
                deviceModel: device?.product?.product_code?.substring(0, 5) || device?.device_model.substring(0, 5),
                deviceName: device.alias_name || device.device_name || device.name,
                deviceModelName: device?.product?.name,
                invalid: false
            }
        }

        return { deviceId, deviceModel: '', deviceName: '', deviceModelName: '', invalid: true }
    }
}