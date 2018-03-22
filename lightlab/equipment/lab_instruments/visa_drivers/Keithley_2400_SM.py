import numpy as np
import time

from . import VISAInstrumentDriver
from lightlab.equipment.abstract_drivers import Configurable

class Keithley_2400_SM(VISAInstrumentDriver, Configurable):
    ''' A Keithley 2400 driver.

        Manual: http://research.physics.illinois.edu/bezryadin/labprotocol/Keithley2400Manual.pdf

        Capable of sourcing current and measuring voltage, such as a Keithley

        Also provides interface methods for measuring resistance and measuring power

        Todo:
            Protection attributes could instead be properties to simplify.
            It is preferable to have 1 way to do 1 thing.
            Possible exception: setCurrentMode(protectionVoltage=1) should still be allowed.

            Consider privatizing setCurrentMode/setVoltageMode. Just set the voltage and it will change into that mode.
    '''
    autoDisable = None  # in seconds. NOT IMPLEMENTED
    _latestCurrentVal = 0
    _latestVoltageVal = 0

    def __init__(self, name=None, address=None, **kwargs):
        '''
            Args:
                hostID (str): There are three different hosts in the lab, \'andromeda'\, \'corinna'\,\'olympias'\
                protectionVoltage : The unit of compliance voltage is Volt.
        '''
        VISAInstrumentDriver.__init__(self, name=name, address=address, **kwargs)
        Configurable.__init__(self, headerIsOptional=False, verboseIsOptional=False)

        self.setProtectionVoltage(kwargs.pop("protectionVoltage", 4))
        self.setProtectionCurrent(kwargs.pop("protectionCurrent", 200E-3))

        self.currStep = kwargs.pop("currStep", 1.0E-3)
        self.voltStep = kwargs.pop("voltStep", 0.1)

    def startup(self):
        self.write('*RST')

    def setPort(self, port):
        if port == 'Front':
            self.setConfigParam('ROUT:TERM', 'FRON')
        elif port == 'Rear':
            self.setConfigParam('ROUT:TERM', 'REAR')

    def __setSourceMode(self, isCurrentSource):
        # TODO: make proper automata flowchart for this.
        if isCurrentSource:
            sourceStr, meterStr = ('CURR', 'VOLT')
        else:
            sourceStr, meterStr = ('VOLT', 'CURR')
        self.setConfigParam('SOURCE:FUNC', sourceStr)
        self.setConfigParam('SOURCE:{}:MODE'.format(sourceStr), 'FIXED')
        self.setConfigParam('SENSE:FUNCTION:OFF:ALL')
        self.setConfigParam('SENSE:FUNCTION:ON', '"{}"'.format(meterStr))
        self.setConfigParam('SENSE:{}:RANGE:AUTO'.format(meterStr), 'ON')
        self.setConfigParam('RES:MODE', 'MAN')  # Manual resistance ranging

    def setVoltageMode(self, protectionCurrent=0.05):
        self.enable(False)
        self.__setSourceMode(isCurrentSource=False)
        self.setProtectionCurrent(protectionCurrent)
        self._configVoltage(0)

    def setCurrentMode(self, protectionVoltage=1):
        self.enable(False)
        self.__setSourceMode(isCurrentSource=True)
        self.setProtectionVoltage(protectionVoltage)
        self._configCurrent(0)

    def _configCurrent(self, currAmps, time_delay=0.0):
        currAmps = float(currAmps)
        currAmps = np.clip(currAmps, a_min=1e-6, a_max=1.)
        if currAmps != 0:
            needRange = 10 ** np.ceil(np.log10(abs(currAmps)))
            self.setConfigParam('SOURCE:CURR:RANGE', needRange)
        self.setConfigParam('SOURCE:CURR', currAmps)
        self._latestCurrentVal = currAmps
        time.sleep(time_delay)

    def _configVoltage(self, voltVolts, time_delay=0.0):
        if voltVolts != 0:
            needRange = 10 ** np.ceil(np.log10(np.abs(voltVolts)))
            self.setConfigParam('SOURCE:VOLT:RANGE', needRange)
        self.setConfigParam('SOURCE:VOLT', voltVolts)
        self._latestVoltageVal = voltVolts
        time.sleep(time_delay)

    def setCurrent(self, currAmps):
        ''' This leaves the output on indefinitely '''
        currTemp = self._latestCurrentVal
        if not self.enable() or self.currStep is None:
            self._configCurrent(currAmps)
        else:
            nSteps = int(np.floor(abs(currTemp - currAmps) / self.currStep))
            for curr in np.linspace(currTemp, currAmps, 1 + nSteps)[1:]:
                self._configCurrent(curr)

    def setVoltage(self, voltVolts):
        voltTemp = self._latestVoltageVal
        if not self.enable() or self.voltStep is None:
            self._configCurrent(voltVolts)
        else:
            nSteps = int(np.floor(abs(voltTemp - voltVolts) / self.voltStep))
            for volt in np.linspace(voltTemp, voltVolts, 1 + nSteps)[1:]:
                self._configCurrent(volt)

    def getCurrent(self):
        currGlob = self.getConfigParam('SOURCE:CURR')
        if type(currGlob) is dict:
            currGlob = currGlob['&']
        return currGlob

    def getVoltage(self):
        voltGlob = self.getConfigParam('SOURCE:VOLT')
        if type(voltGlob) is dict:
            voltGlob = voltGlob['&']
        return voltGlob

    def setProtectionVoltage(self, protectionVoltage):
        self.setConfigParam('VOLT:PROT', protectionVoltage)

    def setProtectionCurrent(self, protectionCurrent):
        self.setConfigParam('CURR:PROT', protectionCurrent)

    @property
    def protectionVoltage(self):
        return self.getConfigParam('VOLT:PROT')

    @property
    def protectionCurrent(self):
        return self.getConfigParam('CURR:PROT')

    def measVoltage(self):
        retStr = self.query('MEASURE:VOLT?')
        v = float(retStr.split(',')[0])  # first number is voltage always
        if v >= self.protectionVoltage:
            print('Warning: Keithley compliance voltage of',
                  self.protectionVoltage, 'reached.')
            print('Warning: You are sourcing', v *
                  self._latestCurrentVal * 1e-3, 'mW into the load.')
        return v

    def measCurrent(self):
        retStr = self.query('MEASURE:CURR?')
        i = float(retStr.split(',')[1])  # second number is current always
        if i >= self.protectionCurrent:
            print('Warning: Keithley compliance current of',
                  self.protectionCurrent, 'reached.')
            print('Warning: You are sourcing', i *
                  self._latestVoltageVal * 1e-3, 'mW into the load.')
        return i

    def enable(self, newState=None):
        ''' get/set enable state
        '''
        if newState is False:
            if self.getConfigParam('SOURCE:FUNC') == 'CURR':
                self.setCurrent(0)
            else:
                self.setVoltage(0)
        if newState is not None:
            self.setConfigParam('OUTP:STATE', 1 if newState else 0)
        retVal = self.getConfigParam('OUTP:STATE', forceHardware=True)
        return retVal in ['ON', 1, '1']


class Keithley_2400_SM_noRamp(Keithley_2400_SM):
    ''' Same except with no ramping. You see what you get
    '''
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.voltStep = None
        self.currStep = None

