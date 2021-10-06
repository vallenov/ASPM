#!/bin/python
import configparser
import subprocess as sp
import re
import os
import cx_Oracle
import json
import requests
import time
import traceback
import logging
#from logger import StandardLogging

'''
Снятие метрик
Снимает метрики времени для элементов из ini и записывает в БД в таблицу CRM_GATE.ASTERISK_SIP_PEER_MON на OLAP
Имя текущего сервера, имя удаленного сервера и все прочие настройки прописываются в /usr/local/etc/ASPМ/aspm.inl
Добавление пира:
Добавить
[da10]
host=00.30.102.12
type=peer
context=da10_channel
nat=yes
qualify=yes
insecure=invite,port
disallow=all
allow=g729
allow=ulaw
allow=alaw
prematuremedla=no
dtmfmode=rfc2833
relaxdtmf=yes
rfc2833compensate=no
в файл /etc/asterisk/sip.conf (главное - задать host и сontext)
и перезапустить командой аsterisk -x "sip reload"
возможно, с sudo
все
Важно правильно настроить ini:
s1-название сервера, на котором будет работать этот скрипт
s2- список кратких названий серверов, с которыми будут проводиться замеры. Через запятую. Названия должны совпадать с теми, что в списке
который можно посмотреть с помощью команды asterisk-x "sip show peers"
s1_full - Полное название сервера s1
s2_full - Полные названия серверов s2
[ОРТIONS] - можно менять прямо во время работы скрипта, не останавливая его работу
sleeptime- задержка между запусками основной процедуры
min_delay_value- если значение задержки больше или равно этому значению, запись попадет в таблицу
token - токен для работы с interlayer'ом
'''

class ASPM:

    def _init_(self, interlayer=True): # interlayer если False, то скрипт будет работать с сх_Oracle
        self._connect_server = 'OLAP' # Название сервра, к которому будет подключение в случае работы с сх_Оracle
        self._DB_API = 'f_ASTER_SIP_PEЕР_МON' # Hазвание внешней функции, находящейся в БД
        self._config = configparser.ConfigParser()
        self._use_interlayer = interlayer
        self._config.read(f'/usr/local/etc/ASPM/aspm.ini', encoding="windows-1251")
        self._buffer = []
        self._unreach_list = []
        self._lagger_list = []
        if not self._use_interlayer: self._work_with_oracle()

    def write_from_buffer(self):
        '''Отправка информации из буфера на запись'''
        ins_info = 0
        while ins_info in range(len(self._buffer)):
            pare = f"{self._buffer[ins_info]['s1']} -> {self._buffer[ins_info]['s2']}"
            logging.info(f'Check {pare}')
            
            if self._buffer[ins_info]['status'] == 'UNREACHABLE' and f'{pare}' not in self._unreach_list:
                self.unreach_list.append(pare)
                logging.warning(f'Status is UNREACHABLE!')
                self._send_emai('ASPM ERROR', f'{pare} is UNREACHABLE')
            
            if self._buffer[ins_info]['status'] =='LAGGER' and f'{pare}' not in self._lagger_list:
                self._lagger_list.append(pare)
                logging.warning(f'Status is LAGGER!')
                self._send_email('ASPM ERROR', f'''{pare} is LAGGER {self._buffer[ins_info]['T']} ms)''')

            if self._buffer[ins_info]['status'] == 'OK':
                if pare in self._unreach_list:
                    self._send_email('ASPM info', f'{pare} switch status from UNREACHABLE to OK')
                    self._unreach_list.remove(pare)
                    self._buffer.pop(0)
                    logging.info(f'{pare} switch status from UNREACHABLE to OK')
                    continue
                if pare in self._lagger_list:
                    self._send_email('ASPM info', f'{pare} switch status from LAGGER to OK')
                    self._lagger_list.remove(pare)
                    self._buffer.pop(0)
                    logging.info(f'{pare} switch status from LAGGER to OK')
                    continue
                if self._buffer[ins_info]['T'] > 10:
                    self._send_email('ASPM Warning', f"{pare} Is {self._buffer[ins_info]['T']} ms")
                elif 10 >= self._buffer[ins_info]['T']> int(self._config['OPTIONS']['min_delay_value']):
                    logging.warning(f'''Delay exceeded! min = {self._config['OPTIONS']['min_delay_value']}, current = {self._bufferf[ins_info]['T']}''')
                else:
                    #Если пир найден, имеет статус 'OK' и лимит скорости не превышен
                    logging.info(f'Everything is OK')
                    #self._buffer.pop(0)
                    #continue
            self._buffer[ins_info]['requests'] = 'write_peer'
            print_info = self._buffer[ins_info]
            print_info['token'] = '*****'
            if not self._use_interlayer:
                '''Запись напрямую в БД'''
                logging.info(f'Send to DB: {print_info}')
                self._replytype = self._cursor.var(cx_Oracle.CLOB)
                reply = json.loads(str(self._cursor.callfunc(self._DB_API, self._replytype, [json.dumps(self._buffer[ins_info]),])))
                logging.info(f'Get reply from DB: {reply}')
            else:
                '''Запись через interlayer'''
                try:
                    logging.info(f'Send to interlayer: {print_info}')
                    reply = requests.post('http://something:0000/f_aster_sip_peep_mon', json=self._buffer[ins_info])
                    reply = json.loads(reply.text)
                    logging.info(f'Get reply from interlayer: {reply}')
                except requests.exceptions.ConnectionError as rex:
                    logging.info(f'Exception when connect to interlayer. Switch to DB')
                    self._work_with_oracle()
                    self._use_interlayer = False
                    self.write_from_buffer()
                except Exception as e:
                    logging.info(f'Unrecognize reply from interlayer: {reply}\nException:(e)')
            try:
                if reply['status'] !='error':
                    self._buffer.pop(0)
                else:
                    ins_info += 1
            except Exception as e:
                logging.info(f'Unrecognize reply: {reply}')
                #finally:
                # ins_info = 1
        logging.info('Finish')

    def _work_with_oracle(self):
        '''Подключение к БД и открытие курсора'''
        try:
            self._conn = cx_Oracle.connect\
                (
                dsn = self._config[self._connect_server]['dsn'],
                user = self._config[self._connect_server]['username'],
                password = self._config[self._connect_server]['password']
                )
            self._cursor = self._conn.cursor()
        except Exception as e:
            logging.info(f'Exception {e} when connect to DB. Switch to interlayer')
            self._use_interlayer = True

    def get_sleeptime(self):
        '''Получение задержки между срабатываниями процедуры main()'''
        return int(self._config['OPTIONS']['sleeptime'])

    def init_log_and_conf(self):
        '''Обновление настроек inl (что бы оказывать воздействие на работу программы без остановки процесса) и логгера (для
        правильного логгирования по дням)'''
        my_preference = {
            "log_mode":"cir",
            "ip":"00.4.18.47",
            "port":9999,
            "is_test": False,
            "log_directory":'/opt/ASPM/logs'}
        if not os.path.exists('/opt/ASPM/logs'):
            os.mkdir('/opt/ASPM/logs')
        #logging = Standard_Logging.setup_logger(project_name='ASPM', log_file_pref='ASPM_', **my_preference)
        logging.info('Start')
        try:
            self._config.read(f'/usr/local/etc/ASPM/aspm.ini', encoding="windows-1251")
        except Exception as e:
            logging.error('ini file not found!')

    def _send_email(self, subject, msg, to='email-address'):
        send_email = {}
        send_email['requests'] = 'send_email'
        if not int(self._config['OPTIONS']['dev']):
            send_email['to'] = self._config['MAIL']['addresses']
            logging.warning(f"Send email to {self._config['MAIL']['addresses']}")
        else:
            send_email['to'] = to
            logging.warning(f"Send email to {to}")
            send_email['subject'] = subject
            send_email['msg'] = msg
        if not self._use_interlayer:
            self_replytype = self._cursor.varlox_Oracle.CLOB()
            reply = json.loads(str(self._cursor.callfunc(self._DB_API, self._replytype, [json.dumps(send_email),])))
            logging.info(f'Get reply from DB: {reply}')
        else:
            try:
                reply = requests.post('http://something:9999/db/f_aster_sip_peep_mon', json=send_email)
            except requests.exceptions.ConnectionError as rex:
                logging.info(f'exception when connect to interlayer. Switch to DB')
                self._work_with_oracle()
                self._use_interlayer = False
            else:
                logging.info(f'Get reply from interlayer: {reply.text}')

    def add_to_buffer(self):
        '''Добавление записей в буфер'''
        middle_dict = {}
        garb = sp.check_output(['sudo', 'asterisk', '-x', 'sip show peers'])
        lst = str(garb)[2:].split(r'\n')
        lst = lst(1-2)
        for string in lst:
            space = string.find('')
            middle_dict[string[:space]] = string[space:]
        s2 = self._config['SERVERS']['s2']
        s2_full = self._config['SERVERS']['s2_full']
        if',' in s2:
            dist_servers = s2.split(',')
            full_name_servers = s2_full.split(',')
            if len(dist_servers) != len(full_name_servers):
                logging.error(f"Error in ini file")
                exit()
        else:
            dist_servers = 0
            dist_servers.append(s2)
        #
        for server, full_name in zip(dist_servers, full_name_servers):
            final_dict = 0
            final_dict['token'] = self._config['OPTIONS']['token']
            final_dict['s1'] = self._config['SERVERS']['s1_full']
            final_dict['s2'] = full_name
            try:
                if 'OK' in middle_dict[server]:
                    final_dict['status'] = 'OK'
                    tmp = re.search('\d+ ms', middle_dict[server])
                    final_dict['T'] = int(tmp[0][:-3])
                elif 'LAGGER' in middle_dict[server]:
                    final_dict['status'] = 'LAGGER'
                    tmp = re.search('\d+ ms', middle_dict[server])
                    final_dict['T'] = int(tmp[0][:-3])
                elif 'UNREACHABLE' in middle_dict[server]:
                    final_dict['status'] = 'UNREACHABLE'
                    final_dict['T'] = -1
                else:
                    final_dict['status'] = 'ERROR'
                    final_dict['T'] = -1
                    logging.error(f'Something is wrong!')
            except KeyError as e:
                logging.warning(f'Peer (server) not found')
                continue
            except Exception as e:
                logging.error(f'Unrecognize Exception ({e})\nTraceback: {traceback.format_exc()}')
                continue
            self._buffer.append(final_dict)
            #self._write_peer(final_dict)
            #if not self._use_interlayer:
            # self._conn.commit()
        #if not self._use_interlayer:
        # self._cursor.close()
        # self._conn.close()
    
if __name__ == "__main__":
    A = ASPM()
    while True:
        A.init_log_and_confl()
        A.add_to_buffer()
        A.write_from_buffer()
        #Очистка настроек лотирования
        A.logging.handlers = 0
        time.sleep(A.get_sleeptime())

