/* Reference data, policy rules and demo seed data for Brightwater Expenses. */
(function () {
  'use strict';

  const USER = Object.freeze({
    name: 'Maya Patel',
    initials: 'MP',
    department: 'Operations',
    title: 'Operations Coordinator',
    email: 'maya.patel@brightwater.example',
    employeeId: 'BW-04718',
    office: 'Rotterdam, Waalhaven',
    manager: 'Daniel Okafor',
    managerTitle: 'Head of Operations',
    iban: 'NL•• •••• •••• 4821'
  });

  const CATEGORIES = Object.freeze([
    { id: 'Travel', icon: 'travel' },
    { id: 'Meals', icon: 'meals' },
    { id: 'Accommodation', icon: 'accommodation' },
    { id: 'Office supplies', icon: 'office' },
    { id: 'Mileage', icon: 'mileage' },
    { id: 'Other', icon: 'other' }
  ]);

  const COST_CENTRES = Object.freeze([
    { id: 'OPS-210', name: 'Operations' },
    { id: 'FIN-110', name: 'Finance' },
    { id: 'WHS-330', name: 'Warehouse' },
    { id: 'TRN-240', name: 'Transport planning' },
    { id: 'CS-150', name: 'Customer service' }
  ]);

  /* Fixed reference rates to EUR used for policy checks (Finance updates monthly). */
  const CURRENCIES = Object.freeze([
    { code: 'EUR', rate: 1 },
    { code: 'GBP', rate: 1.17 },
    { code: 'USD', rate: 0.92 },
    { code: 'CHF', rate: 1.06 },
    { code: 'PLN', rate: 0.23 },
    { code: 'DKK', rate: 0.134 }
  ]);

  const POLICY = Object.freeze({
    receiptThreshold: 25,
    mealLimitPerPerson: 60,
    submissionWindowDays: 30,
    mileageRate: 0.3,
    purposeMinLength: 10
  });

  const STATUSES = Object.freeze(['Draft', 'Submitted', 'Approved', 'Reimbursed']);

  function at(date, time) {
    return date + 'T' + time + ':00';
  }

  const SEED_EXPENSES = Object.freeze([
    {
      id: 'EXP-1042', date: '2026-10-22', merchant: 'NS International', category: 'Travel',
      amount: 129.9, currency: 'EUR', costCentre: 'OPS-210', attendees: 1,
      purpose: 'Return train Rotterdam to Antwerp for the quarterly carrier review with Van Dijk Transport.',
      status: 'Submitted', receiptName: 'ns-international-ticket.pdf',
      history: { created: at('2026-10-22', '18:04'), submitted: at('2026-10-23', '09:12') }
    },
    {
      id: 'EXP-1036', date: '2026-10-24', merchant: 'Uber', category: 'Travel',
      amount: 23.1, currency: 'EUR', costCentre: 'OPS-210', attendees: 1,
      purpose: 'Taxi from Rotterdam Centraal to the Maasvlakte terminal after the late shift handover.',
      status: 'Draft', receiptName: null,
      history: { created: at('2026-10-24', '21:37') }
    },
    {
      id: 'EXP-1041', date: '2026-10-18', merchant: 'Hotel Arcadia Antwerpen', category: 'Accommodation',
      amount: 164, currency: 'EUR', costCentre: 'OPS-210', attendees: 1,
      purpose: 'One night stay for the Antwerp port partner workshop.',
      status: 'Approved', receiptName: 'hotel-arcadia-invoice.pdf',
      history: { created: at('2026-10-19', '08:40'), submitted: at('2026-10-19', '08:44'), approved: at('2026-10-20', '14:02') }
    },
    {
      id: 'EXP-1040', date: '2026-10-14', merchant: 'Brasserie Lemaire', category: 'Meals',
      amount: 96.4, currency: 'EUR', costCentre: 'OPS-210', attendees: 2,
      purpose: 'Working dinner with the Moerdijk depot manager to plan the winter peak schedule.',
      status: 'Reimbursed', receiptName: 'brasserie-lemaire.jpg',
      history: { created: at('2026-10-14', '22:10'), submitted: at('2026-10-15', '08:30'), approved: at('2026-10-15', '16:45'), financeChecked: at('2026-10-21', '10:20'), reimbursed: at('2026-10-23', '07:00') }
    },
    {
      id: 'EXP-1039', date: '2026-10-09', merchant: 'Mileage: Rotterdam to Moerdijk depot', category: 'Mileage',
      amount: 25.8, currency: 'EUR', costCentre: 'WHS-330', attendees: 1,
      purpose: 'Site visit to the Moerdijk depot for the racking safety inspection, 86 km return.',
      status: 'Reimbursed', receiptName: null, distanceKm: 86,
      history: { created: at('2026-10-09', '17:15'), submitted: at('2026-10-09', '17:18'), approved: at('2026-10-10', '09:05'), financeChecked: at('2026-10-14', '11:30'), reimbursed: at('2026-10-16', '07:00') }
    },
    {
      id: 'EXP-1038', date: '2026-10-06', merchant: 'Office Centre Rotterdam', category: 'Office supplies',
      amount: 47.35, currency: 'EUR', costCentre: 'OPS-210', attendees: 1,
      purpose: 'Label printer tape and clipboards for the inbound dock team.',
      status: 'Reimbursed', receiptName: 'office-centre-receipt.jpg',
      history: { created: at('2026-10-06', '12:22'), submitted: at('2026-10-06', '12:25'), approved: at('2026-10-07', '10:11'), financeChecked: at('2026-10-08', '15:40'), reimbursed: at('2026-10-09', '07:00') }
    },
    {
      id: 'EXP-1037', date: '2026-09-29', merchant: 'KLM Royal Dutch Airlines', category: 'Travel',
      amount: 286.4, currency: 'EUR', costCentre: 'OPS-210', attendees: 1,
      purpose: 'Return flight Amsterdam to Hamburg for the customs broker onboarding session.',
      status: 'Reimbursed', receiptName: 'klm-e-ticket.pdf',
      history: { created: at('2026-09-29', '19:02'), submitted: at('2026-09-30', '08:15'), approved: at('2026-09-30', '13:50'), financeChecked: at('2026-10-02', '09:30'), reimbursed: at('2026-10-02', '07:00') }
    },
    {
      id: 'EXP-1035', date: '2026-09-22', merchant: 'Albert Heijn', category: 'Other',
      amount: 31.75, currency: 'EUR', costCentre: 'OPS-210', attendees: 1,
      purpose: 'Refreshments for the warehouse safety briefing with the night shift.',
      status: 'Reimbursed', receiptName: 'albert-heijn-receipt.jpg',
      history: { created: at('2026-09-22', '16:48'), submitted: at('2026-09-22', '16:50'), approved: at('2026-09-23', '09:12'), financeChecked: at('2026-09-24', '14:05'), reimbursed: at('2026-09-25', '07:00') }
    }
  ]);

  const SEED_APPROVALS = Object.freeze([
    {
      id: 'EXP-2187', employee: 'Jonas Weber', initials: 'JW', role: 'Shift lead, Warehouse',
      date: '2026-10-26', merchant: 'Q-Park Rotterdam Centrum', category: 'Travel', amount: 18.5, currency: 'EUR',
      purpose: 'Parking during the customer audit at the Waalhaven office.', status: 'Pending', receipt: true
    },
    {
      id: 'EXP-2184', employee: 'Elena Rossi', initials: 'ER', role: 'Transport planner',
      date: '2026-10-23', merchant: 'Restaurant De Zwarte Kat', category: 'Meals', amount: 112, currency: 'EUR',
      purpose: 'Lunch with two Maersk account managers to review the Q4 capacity plan.', status: 'Pending', receipt: true, attendees: 3
    },
    {
      id: 'EXP-2179', employee: 'Tomasz Nowak', initials: 'TN', role: 'Inventory analyst',
      date: '2026-10-21', merchant: 'Coolblue', category: 'Office supplies', amount: 38.9, currency: 'EUR',
      purpose: 'Replacement barcode scanner cable for cycle counting.', status: 'Pending', receipt: true
    }
  ]);

  const SEED_SETTINGS = Object.freeze({
    defaultCurrency: 'EUR',
    defaultCostCentre: 'OPS-210',
    notifyEmail: true,
    notifyTeams: true,
    notifyWeekly: false
  });

  window.BWData = Object.freeze({
    USER: USER,
    CATEGORIES: CATEGORIES,
    COST_CENTRES: COST_CENTRES,
    CURRENCIES: CURRENCIES,
    POLICY: POLICY,
    STATUSES: STATUSES,
    SEED_EXPENSES: SEED_EXPENSES,
    SEED_APPROVALS: SEED_APPROVALS,
    SEED_SETTINGS: SEED_SETTINGS
  });
})();
