import 'dotenv/config';
import express from 'express';
import { EufyClean } from './';
import { MqttConnect } from './controllers/MqttConnect';

const eufyClean = new EufyClean(process.env.EUFY_USERNAME, process.env.EUFY_PASSWORD);
let _device: MqttConnect;

const app = express();

const scenes: {[sceneName: string]: number} = {
    // full home daily clean: 1
    // full home deep clean: 2
    // Post-Meal Clean: 3
    morning: 4,
    afternoon: 5,
    weekly: 6,
    home: 1,
}

const getDevice = async (deviceId?: string) => {
    if (_device) return _device;

    await eufyClean.init();
    const devices = await eufyClean.getAllDevices();
    if (!deviceId) deviceId = devices.find(d => deviceId ? d.deviceId === deviceId : d).deviceId;
    if (!deviceId) return;
    _device = await eufyClean.initDevice({ deviceId });
    await _device.connect();

    return _device;
}

app.get('/clean/:scene', async (req, res) => {
    const { scene } = req.params;
    const sceneId = scenes[scene];
    if (sceneId === undefined) {
        res.status(400).send('Invalid scene');
        return null;
    }

    const device = await getDevice();
    await device.sceneClean(sceneId);

    res.status(200).send('Cleaning');
});

app.get('/stop', async (req, res) => {
    const device = await getDevice();
    await device.stop();
    await device.goHome();
    res.status(200).send('Stopped');
});

app.get('/status', async (req, res) => {
    const device = await getDevice();
    const status = await device.getWorkStatus();
    res.status(200).send(status);
});

app.listen(3000, () => {
    console.log('Server running on port 3000');
});

// getDevice().then(async device => {
//     await device.connect();
//     let status = null;
//     device.robovacData.subscribe(data => {
//         console.log('Data:', data);
//     });
//     device.getWorkStatus().then(status => {
//         console.log('Status:', status);
//     });
// });