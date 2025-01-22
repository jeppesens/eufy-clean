// Communication with the Eufy cloud - This goes via MQTT
// This is only supported for "new" devices like the RoboVac X10 and RoboVac S1
import fs from 'fs';
import mqtt from 'mqtt';
import { EufyLogin } from '../controllers/Login';
import { sleep } from '../lib/utils';
import { SharedConnect } from './SharedConnect';

export class MqttConnect extends SharedConnect {
    private mqttClient: any;
    private mqttCredentials: any;
    private openudid: string;
    private eufyCleanApi: EufyLogin;

    constructor(config: { deviceId: string, deviceModel: string, debug?: boolean }, openudid: string, eufyCleanApi: EufyLogin) {
        super(config);

        this.deviceId = config.deviceId;
        this.deviceModel = config.deviceModel
        this.config = config;

        this.debugLog = config.debug || false;

        this.openudid = openudid;
        this.eufyCleanApi = eufyCleanApi;
    }

    async connect() {
        await this.eufyCleanApi.login({ mqtt: true, tuya: false });

        await this.connectMqtt(this.eufyCleanApi.mqttCredentials);
        await this.updateDevice(true);
        await sleep(2000); // Make sure the device is ready
    }


    public async updateDevice(checkApiType = false) {
        try {
            if (!checkApiType) return;

            const device = await this.eufyCleanApi.getMqttDevice(this.deviceId);

            if (checkApiType) {
                await this.checkApiType(device?.dps);
            }

            await this.mapData(device?.dps)
        } catch (error) {
            console.log(error)
        }
    }


    public async connectMqtt(mqttCredentials): Promise<void> {
        if (mqttCredentials) {
            console.info('MQTT Credentials found');

            this.mqttCredentials = mqttCredentials;

            console.info('Setup MQTT Connection', {
                clientId: `android-${this.mqttCredentials.app_name}-eufy_android_${this.openudid}_${this.mqttCredentials.user_id
                    }-${Date.now()}`,
                username: this.mqttCredentials.thing_name
            });

            if (this.mqttClient) {
                this.mqttClient.end();
            }
            const c1 = Buffer.from(this.mqttCredentials.certificate_pem, 'utf8');
            fs.writeFileSync('ca2.pem', c1);
            const c2 = Buffer.from(this.mqttCredentials.private_key, 'utf8');
            fs.writeFileSync('key2.key', c2);
            this.mqttClient = await mqtt.connect('mqtt://' + this.mqttCredentials.endpoint_addr, {
                clientId: `android-${this.mqttCredentials.app_name}-eufy_android_${this.openudid}_${this.mqttCredentials.user_id
                    }-${Date.now()}`,
                username: this.mqttCredentials.thing_name,
                cert: Buffer.from(this.mqttCredentials.certificate_pem, 'utf8'),
                key: Buffer.from(this.mqttCredentials.private_key, 'utf8'),
                path: '/',
            });

            this.setupListeners();
        }
    }

    setupListeners() {
        this.mqttClient.on('connect', () => {
            console.info('Connected to MQTT');
            console.debug(`Subscribe to cmd/eufy_home/${this.deviceModel}/${this.deviceId}/res`);
            this.mqttClient && this.mqttClient.subscribe(`cmd/eufy_home/${this.deviceModel}/${this.deviceId}/res`);
            //this.mqttClient && this.mqttClient.subscribe(`smart/mb/in/${this.deviceId}`);
        });

        this.mqttClient.on('message', async (topic, message) => {
            const messageParsed = JSON.parse(message.toString());

            console.debug(`Received message on ${topic}: `, messageParsed?.payload?.data);

            await this.mapData(messageParsed?.payload?.data)
        });

        this.mqttClient.on('error', (error) => {
            console.error(`MQTT Error: ${error}`);
        });
        this.mqttClient.on('close', () => {
            console.error('MQTT Connection closed');
        });
        this.mqttClient.on('reconnect', () => {
            console.info('MQTT Reconnect');
        });
        this.mqttClient.on('offline', () => {
            console.error('MQTT Offline');
        });
        this.mqttClient.on('end', () => {
            console.info('MQTT End');
        });
    }

    async sendCommand(dataPayload) {
        try {
            const payload = JSON.stringify({
                account_id: this.mqttCredentials.user_id,
                data: dataPayload,
                device_sn: this.deviceId,
                protocol: 2,
                t: Date.now(),
            });

            const mqqtVal = {
                head: {
                    client_id: `android-${this.mqttCredentials.app_name}-eufy_android_${this.openudid}_${this.mqttCredentials.user_id}`,
                    cmd: 65537,
                    cmd_status: 2,
                    msg_seq: 1,
                    seed: '',
                    sess_id: `android-${this.mqttCredentials.app_name}-eufy_android_${this.openudid}_${this.mqttCredentials.user_id}`,
                    sign_code: 0,
                    timestamp: Date.now(),
                    version: '1.0.0.1',
                },
                payload
            }

            if (this.debugLog) console.debug(JSON.stringify(mqqtVal));

            console.debug(`Sending command to device ${this.deviceId}`, payload);

            this.mqttClient.publish(`cmd/eufy_home/${this.deviceModel}/${this.deviceId}/req`, JSON.stringify(mqqtVal));
            // this.mqttClient.publish(`smart/mb/out/${this.deviceId}`);
        } catch (error) {
            console.error(error)
        }

    }
}