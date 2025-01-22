import 'dotenv/config';
import { EufyClean } from './';


const setup = async () => {
    const eufyClean = new EufyClean(process.env.EUFY_USERNAME, process.env.EUFY_PASSWORD);
    await eufyClean.init();
    const devices = await eufyClean.getAllDevices();
    console.log(devices);

    const deviceId = devices.find(d => d)?.deviceId;
    if (!deviceId) return;
    const device = await eufyClean.initDevice({ deviceId, ip: '10.0.1.56' });
    await device.connect();
    console.log(device);
    // await device.setCleanParam({ cleanType: 'SWEEP_ONLY' });
    // await device.sceneClean(0);
    // await device.sceneClean
    // await device.play();
    await device.goHome();
}

setup();
