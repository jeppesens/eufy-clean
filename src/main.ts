import 'dotenv/config';
import { EufyClean } from './';


const setup = async () => {
    const eufyClean = new EufyClean(process.env.EUFY_USERNAME, process.env.EUFY_PASSWORD);
    await eufyClean.init();
    await eufyClean.init();
    const devices = await eufyClean.getAllDevices();
    console.log(devices);

    const deviceId = devices.find(d => d)?.deviceId;
    if (!deviceId) return;
    const device = await eufyClean.initDevice({ deviceId, ip: '10.0.1.56' });
    await device.connect();
    console.log(device);
    // await device.setCleanParam({ cleanType: 'SWEEP_ONLY' });
    await device.sceneClean(3);
    // await device.sceneClean
    // setTimeout(async () => {
    //     await device.goHome();
    // }, 60 * 1000);
    // await device.play();
}

setup();
