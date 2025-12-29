class Base:
    def __init__(self):
        self.dps_map = {
            'PLAY_PAUSE': '152',
            'DIRECTION': '155',
            'WORK_MODE': '153',
            'WORK_STATUS': '153',
            'CLEANING_PARAMETERS': '154',
            'CLEANING_STATISTICS': '167',
            'ACCESSORIES_STATUS': '168',
            'GO_HOME': '173',
            'CLEAN_SPEED': '158',
            'FIND_ROBOT': '160',
            'BATTERY_LEVEL': '163',
            'STATION_STATUS': '173',
            'ERROR_CODE': '177',
        }
        self.robovac_data = {}

    async def connect(self):
        raise NotImplementedError('Not implemented')
