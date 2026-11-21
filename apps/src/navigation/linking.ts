import { LinkingOptions } from '@react-navigation/native';
import { RootStackParamList } from '../types/navigation';

const linking: LinkingOptions<RootStackParamList> = {
    prefixes: ['confio://', 'https://confio.lat', 'https://www.confio.lat'],
    // A QR shared from another app (iOS Share Extension) is opened by
    // useSharedQr in Pagar, not by a route of its own.
    filter: (url) => !/^confio:\/\/shared-qr/i.test(url),
    config: {
        screens: {
            Main: {
                screens: {
                    VerifyTransaction: 'verify/:hash',
                    PaymentConfirmation: 'pay/:invoiceId',
                    Memberships: 'memberships',
                    Verification: 'verification',
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
