import { createRef } from 'react';
import { ApolloClient, ApolloLink, concat, InMemoryCache, gql} from '@apollo/client';
import { WebSocketLink } from '@apollo/client/link/ws';
import { SubscriptionClient } from 'subscriptions-transport-ws';
import { onError } from '@apollo/client/link/error';

import LanguagePack from './Components/LanguagePack';

export const DEBUG = false;
const WEBSOCKET_BASE_URL =
	DEBUG ? 'ws://127.0.0.1:8000/graphql/' : 'wss://confio.me/graphql/';
const HTTP_BASE_URL =
	DEBUG ? 'http://127.0.0.1:8000' :  'https://confio.me';
const authObservable = createRef();

class WebSocketService {

	constructor() {
		this.socketRef = null;
		this.initialize();
	}

	initialize = () => {
		if (this.socketRef) {
			this.client.close();
			return;
		}
		const client = new SubscriptionClient(WEBSOCKET_BASE_URL, {
			reconnect: true,
			lazy: true,
		});
		client.maxConnectTimeGenerator.duration = () => client.maxConnectTimeGenerator.max // Workaround for earlier closurer of websocket
		client.onError(error => {
			if (error?.message?.includes('Network'))
				alert(LanguagePack({ text: 'noInternetConnection', lang: (navigator.languages && navigator.languages.length) ? navigator.languages[0] : navigator.language}));
		}); // No Internet Connection
		this.client = client;
		const webSocketLink = new WebSocketLink(client);
		const logoutLink = onError(({ graphQLErrors, networkError }) => {
			if (graphQLErrors)
				graphQLErrors.map(({ message, locations, path }) => {
					if (message === 'Login required') {
						alert(LanguagePack({ text: 'pleaseLogin', lang: (navigator.languages && navigator.languages.length) ? navigator.languages[0] : navigator.language }));
						this.logout();
					} else if (message === 'Shut down') {
						alert(LanguagePack({ text: 'serverIsTemporarilyShutDownPleaseWaitForAMoment', lang: (navigator.languages && navigator.languages.length) ? navigator.languages[0] : navigator.language }));
					} else
						console.log(`[GraphQL error]: Message: ${message}, Location: ${JSON.stringify(locations)}, Path: ${path}`);
				});
			if (networkError)
				alert(`[Network error]: ${networkError}`);
		});
		const updateOnlineMiddleWare = new ApolloLink((operation, forward) => {
			this.resetIntervalForUpdateOnline();
			return forward(operation);
		});
		this.cache = new InMemoryCache({
			dataIdFromObject: obj => obj.slug ? `${obj.__typename}-${obj.slug}` : null,
			typePolicies: {
				Query: {
					fields: {
						account(_, { args, toReference }) {
							return toReference({
								__typename: 'AccountType',
								currency: args.currency,
								slug: args.slug,
							});
						},
						market(_, { args, toReference }) {
							return toReference({
								__typename: 'MarketType',
								buyerCurrency: args.buyerCurrency,
								sellerCurrency: args.sellerCurrency,
								name: args.name,
								slug: args.slug,
							});
						},
					}
				},
			}
		});

		this.socketRef = new ApolloClient({
			link: logoutLink.concat(concat(updateOnlineMiddleWare, webSocketLink)),
			cache: this.cache,
			resolvers: {
			},
			fetchOptions: {
				mode: 'no-cors',
			},
		});
		this.writeQuery(
			`
				{
					isLoggedIn
					language
				}
			`, {},
			{
				isLoggedIn: null,
				language: (navigator.languages && navigator.languages.length) ? navigator.languages[0] : navigator.language,
			}
		);
	}

	watchQuery = (query, variables={}, fetchPolicy='cache-first', errorPolicy='all') => {
		return this.socketRef.watchQuery({
			query: gql`${query}`,
			variables,
			fetchPolicy,
			errorPolicy
		});
	}

	query = (query, variables={}, fetchPolicy='no-cache', errorPolicy='all') => {
		return this.socketRef.query({
			query: gql`${query}`,
			variables,
			fetchPolicy,
			errorPolicy
		});
	}

	mutate = (mutation, variables={}, fetchPolicy=null, errorPolicy='all', optimisticResponse=null, update=null) => {
		const options = {
			mutation: gql`${mutation}`,
			variables,
			errorPolicy,
			optimisticResponse,
			update,
		};
		if (fetchPolicy)
			options.fetchPolicy = 'no-cache';
		//Mutations only support a 'no-cache' fetchPolicy. If you don't want to disable the cache, remove your fetchPolicy setting to proceed with the default mutation behavior.
		return this.socketRef.mutate(options);
	}

	subscribe = (subscription, variables={}, fetchPolicy=null) => {
		const options = {
			query: gql`${subscription}`,
			variables,
		}
		if (fetchPolicy)
			options.fetchPolicy = fetchPolicy;
		return this.socketRef.subscribe(options);
	}

	readQuery = (query, variables=null) => {
		const options = {
			query: gql`${query}`,
		}
		if (variables)
			options.variables = variables;
		return this.socketRef.readQuery(options);
	};

	writeQuery = (query, variables=null, data) => {
		const options = {
			query: gql`${query}`,
			data: data,
		}
		if (variables)
			options.variables = variables;
		return this.socketRef.writeQuery(options);
	};

	logout = async () => {
		const asyncStorageKeys = Object.keys(localStorage);
		if (asyncStorageKeys.length > 0)
			await localStorage.clear();
		await this.socketRef.clearStore(); // Don't use resetStore() to avoid cache crash from watchqueries
		this.writeQuery(
			`
				{
					isLoggedIn
					language
				}
			`, {},
		{ // write default data to avoid crash
			isLoggedIn: false,
			language: (navigator.languages && navigator.languages.length) ? navigator.languages[0] : navigator.language,
		});
		await authObservable.current.refetch(); // Don't use reFetchObservableQueries to avoid refetching unmounted watchqueries
	}

	resetIntervalForUpdateOnline = () => {
		clearInterval(this.updateOnlineInterval);
		this.updateOnlineInterval = setInterval(this.updateOnline, 25000);
	}

	updateOnline = () => {
		return this.socketRef.query({
			query: gql`query updateOnline {
				updateOnline
			}`,
			fetchPolicy: 'no-cache',
		});
	}

	logEvent = event => {
		const clientActionTime = new Date();
		const timezone = Intl.DateTimeFormat().resolvedOptions().timeZone;
		const lastEventTime = this?.lastEventTime ?? clientActionTime;
		this.mutate(`
			mutation (
				$eventName: String!
				$clientActionTime: DateTime!
				$timezone: String!
				$deviceId: String!
				$platform: String!
				$consumedTimeBeforeAction: Int!
				$charValue1: String
				$charValue2: String
				$intValue1: Int
				$intValue2: Int
			) {
				logEvent (input: {
					eventName: $eventName
					clientActionTime: $clientActionTime
					timezone: $timezone
					deviceId: $deviceId
					platform: $platform
					consumedTimeBeforeAction: $consumedTimeBeforeAction
					charValue1: $charValue1
					charValue2: $charValue2
					intValue1: $intValue1
					intValue2: $intValue2
				}) {
					ok
				}
			}
		`, {
			...event,
			clientActionTime: clientActionTime,
			timezone: timezone,
			deviceId: 'web',
			platform: 'web',
			consumedTimeBeforeAction: event?.consumedTimeBeforeAction ?? clientActionTime.getTime() - lastEventTime.getTime(),
		}, 'no-cache');
		this.lastEventTime = clientActionTime;
	}
}

var WebSocketInstance = WebSocketInstance ? WebSocketInstance : new WebSocketService();

export { HTTP_BASE_URL, authObservable };
export default WebSocketInstance;