class Base:
    def __init__(self):
        self.legacy_dps_map = {
            'PLAY_PAUSE': '2',
            'DIRECTION': '3',
            'WORK_MODE': '5',
            'WORK_STATUS': '15',
            'CLEANING_PARAMETERS': '154',
            'CLEANING_STATISTICS': '167',
            'ACCESSORIES_STATUS': '168',
            'GO_HOME': '101',
            'CLEAN_SPEED': '102',
            'FIND_ROBOT': '103',
            'BATTERY_LEVEL': '104',
            'ERROR_CODE': '106',
        }

        self.novel_dps_map = {
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
            'ERROR_CODE': '177',
        }

        self.dps_map = self.legacy_dps_map

    async def connect(self):
        raise NotImplementedError('Not implemented')