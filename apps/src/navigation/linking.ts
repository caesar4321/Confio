import { LinkingOptions } from '@react-navigation/native';
import { RootStackParamList } from '../types/navigation';

const linking: LinkingOptions<RootStackParamList> = {
    prefixes: ['confio://', 'https://confio.lat', 'https://www.confio.lat'],
    config: {
        screens: {
            Main: {
                screens: {
                    VerifyTransaction: 'verify/:hash',
                    PaymentConfirmation: 'pay/:invoiceId',
                },
            },
            Auth: {
                screens: {
                    Login: 'login',
                }
            }
        },
    },
};

export default linking;
