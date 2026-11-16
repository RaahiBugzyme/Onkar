import type { GenerationId } from './generations'

export type CompletenessCategory =
  | 'complete'
  | 'mostly_complete'
  | 'partially_complete'
  | 'several_missing'

export interface FictionalDemoProfile {
  id: number
  chatId: number
  name: string
  age: number | null
  gender: 'female' | 'male' | 'non-binary' | null
  city: string
  era: GenerationId
  eraBadge: string
  eraIcon: string
  ringColor: string
  cornerEmoji: string
  vibeTag: string | null
  profession: string | null
  education: string | null
  bio: string | null
  interests: string[]
  relationshipIntentions: string | null
  preferredAgeRange: [number, number] | null
  preferredDistanceKm: number | null
  preferredGenerations: GenerationId[] | null
  completenessCategory: CompletenessCategory
  completenessScore: number // 0-100%
  photos: string[]
  initials: string
  isDemo: true
  isVerified: boolean
  status: 'online' | 'offline'
  lastSeen: string
  isMatch: boolean
  lastMessage?: string
  lastMessageTime?: string
  unread?: boolean
  isNew?: boolean
  compatibilityScore?: number | null
}

function demoAsset(filename: string): string {
  return new URL(`../assets/demo-profiles/${filename}`, import.meta.url).href
}

export const TWENTY_DEMO_PROFILES: FictionalDemoProfile[] = [
  // -------------------------------------------------------------
  // PROFILE 901: Jeet (Complete - 100%) - Initial Match & Conversation
  // -------------------------------------------------------------
  {
    id: 901,
    chatId: 901,
    name: 'Jeet',
    age: 24,
    gender: 'male',
    city: 'Mumbai',
    era: 'zillenial',
    eraBadge: 'Zillenial 🎭',
    eraIcon: '🎭',
    ringColor: '#f59e0b',
    cornerEmoji: '🎭',
    vibeTag: 'Low-key exclusive',
    profession: 'Architect & 3D Visualizer',
    education: 'CEPT University Ahmedabad',
    bio: "Old enough for a mortgage, young enough to not want one. Let's grab specialty coffee, talk brutalist architecture, and wander South Mumbai by night ☕",
    interests: ['specialty coffee', 'brutalist architecture', 'indie vinyl', 'night cycling'],
    relationshipIntentions: 'Long-term relationship with someone who appreciates slow Sundays',
    preferredAgeRange: [22, 28],
    preferredDistanceKm: 25,
    preferredGenerations: ['zillenial', 'genz'],
    completenessCategory: 'complete',
    completenessScore: 100,
    photos: [
      demoAsset('profile-901-primary.jpg'),
      demoAsset('profile-901-gallery-1.jpg'),
      demoAsset('profile-901-gallery-2.jpg'),
    ],
    initials: 'J',
    isDemo: true,
    isVerified: true,
    status: 'offline',
    lastSeen: 'last seen 3d ago',
    isMatch: true,
    lastMessage: 'Say hi! 👋',
    lastMessageTime: '3d ago',
    unread: true,
    isNew: true,
    compatibilityScore: null,
  },

  // -------------------------------------------------------------
  // PROFILE 902: Abhi (Mostly Complete - 85%) - Initial Match
  // Missing: education (null)
  // -------------------------------------------------------------
  {
    id: 902,
    chatId: 902,
    name: 'Abhi',
    age: 22,
    gender: 'male',
    city: 'Bengaluru',
    era: 'genz',
    eraBadge: 'Gen Z 💀',
    eraIcon: '💀',
    ringColor: '#a855f7',
    cornerEmoji: '✌️',
    vibeTag: 'Undefined but vibing',
    profession: 'Electronic Music Producer & Sound Designer',
    education: null,
    bio: "no cap this app lowkey slaps. Producing synthwave in Indiranagar, finding the best filter coffee, soft launch ready fr fr 🎧",
    interests: ['modular synths', 'indie electronica', 'skateboarding', 'filter coffee'],
    relationshipIntentions: 'Casual dating / figuring out my vibe',
    preferredAgeRange: [20, 25],
    preferredDistanceKm: 15,
    preferredGenerations: ['genz', 'zillenial'],
    completenessCategory: 'mostly_complete',
    completenessScore: 85,
    photos: [
      demoAsset('profile-902-primary.jpg'),
      demoAsset('profile-902-gallery-1.jpg'),
      demoAsset('profile-902-gallery-2.jpg'),
    ],
    initials: 'A',
    isDemo: true,
    isVerified: true,
    status: 'offline',
    lastSeen: 'last seen 1h ago',
    isMatch: true,
    lastMessage: "Hey! What's up?",
    lastMessageTime: '1h ago',
    unread: true,
    isNew: true,
    compatibilityScore: null,
  },

  // -------------------------------------------------------------
  // PROFILE 903: Aman (Partially Complete - 60%) - Initial Match
  // Missing: education, relationshipIntentions, preferredDistanceKm (null)
  // -------------------------------------------------------------
  {
    id: 903,
    chatId: 903,
    name: 'Aman',
    age: 23,
    gender: 'male',
    city: 'Delhi',
    era: 'genz',
    eraBadge: 'Gen Z 💀',
    eraIcon: '💀',
    ringColor: '#a855f7',
    cornerEmoji: '💀',
    vibeTag: 'Caught between',
    profession: 'Stand-up Comic & Writer',
    education: null,
    bio: "Bestie if you're still reading this we should probably just talk already 😂 Chronic overthinker, gym enthusiast, and professional mic dropper.",
    interests: ['stand-up comedy', 'powerlifting', 'late night shawarma', 'podcast binging'],
    relationshipIntentions: null,
    preferredAgeRange: [21, 26],
    preferredDistanceKm: null,
    preferredGenerations: ['genz'],
    completenessCategory: 'partially_complete',
    completenessScore: 60,
    photos: [
      demoAsset('profile-903-primary.jpg'),
      demoAsset('profile-903-gallery-1.jpg'),
      demoAsset('profile-903-gallery-2.jpg'),
    ],
    initials: 'A',
    isDemo: true,
    isVerified: true,
    status: 'offline',
    lastSeen: 'last seen 5h ago',
    isMatch: true,
    lastMessage: "Haha, that's funny 😂",
    lastMessageTime: '5h ago',
    unread: true,
    isNew: true,
    compatibilityScore: null,
  },

  // -------------------------------------------------------------
  // PROFILE 904: Kunal (Mostly Complete - 85%) - Initial Match
  // Missing: preferredGenerations (null)
  // -------------------------------------------------------------
  {
    id: 904,
    chatId: 904,
    name: 'Kunal',
    age: 29,
    gender: 'male',
    city: 'Pune',
    era: 'millennial',
    eraBadge: 'Millennial ⚡',
    eraIcon: '⚡',
    ringColor: '#06b6d4',
    cornerEmoji: '⚡',
    vibeTag: 'Adulting together',
    profession: 'Specialty Coffee Roaster & Micro-bakery Co-founder',
    education: 'Fergusson College Pune',
    bio: "Adulting is challenging but the pour-over is dialed in. Looking for honest conversations, weekend Sahyadri treks, and vinyl listening sessions 🎸",
    interests: ['aeropress brews', 'sahyadri trekking', 'post-rock', 'sourdough baking'],
    relationshipIntentions: 'Serious relationship with someone emotionally grounded',
    preferredAgeRange: [26, 32],
    preferredDistanceKm: 35,
    preferredGenerations: null,
    completenessCategory: 'mostly_complete',
    completenessScore: 85,
    photos: [
      demoAsset('profile-904-primary.jpg'),
      demoAsset('profile-904-gallery-1.jpg'),
      demoAsset('profile-904-gallery-2.jpg'),
    ],
    initials: 'K',
    isDemo: true,
    isVerified: true,
    status: 'offline',
    lastSeen: 'last seen 1d ago',
    isMatch: true,
    lastMessage: "Let's talk sometime.",
    lastMessageTime: '1d ago',
    unread: false,
    isNew: true,
    compatibilityScore: null,
  },

  // -------------------------------------------------------------
  // PROFILE 905: Priya (Mostly Complete - 85%) - Initial Match
  // Missing: preferredDistanceKm (null)
  // -------------------------------------------------------------
  {
    id: 905,
    chatId: 905,
    name: 'Priya',
    age: 25,
    gender: 'female',
    city: 'Hyderabad',
    era: 'zillenial',
    eraBadge: 'Zillenial 🎭',
    eraIcon: '🎭',
    ringColor: '#f59e0b',
    cornerEmoji: '✨',
    vibeTag: 'Half-official',
    profession: 'UX Researcher & Ceramicist',
    education: 'NID Ahmedabad',
    bio: "Half LinkedIn corporate resilience, half BeReal chaos. Throwing pottery on weekends, craving Irani chai, and looking for someone who texts back with good banter ✨",
    interests: ['ceramic pottery', 'irani chai', 'indie cinema', 'golden retrievers'],
    relationshipIntentions: 'Meaningful connection that starts with coffee and great laughs',
    preferredAgeRange: [24, 30],
    preferredDistanceKm: null,
    preferredGenerations: ['zillenial', 'millennial'],
    completenessCategory: 'mostly_complete',
    completenessScore: 85,
    photos: [
      demoAsset('profile-905-primary.jpg'),
      demoAsset('profile-905-gallery-1.jpg'),
      demoAsset('profile-905-gallery-2.jpg'),
    ],
    initials: 'P',
    isDemo: true,
    isVerified: true,
    status: 'offline',
    lastSeen: 'last seen 2d ago',
    isMatch: true,
    lastMessage: 'Hey there! ✨',
    lastMessageTime: '2d ago',
    unread: false,
    isNew: true,
    compatibilityScore: null,
  },

  // -------------------------------------------------------------
  // PROFILE 906: Zara K. (Complete - 100%) - Discover Feed Candidate
  // -------------------------------------------------------------
  {
    id: 906,
    chatId: 906,
    name: 'Zara K.',
    age: 22,
    gender: 'female',
    city: 'Mumbai',
    era: 'genz',
    eraBadge: 'Gen Z 💀',
    eraIcon: '💀',
    ringColor: '#a855f7',
    cornerEmoji: '🧿',
    vibeTag: 'Main character energy',
    profession: 'Fashion Stylist & Creative Director',
    education: 'NIFT Mumbai',
    bio: "It's giving main character energy tbh. Sourcing thrifted streetwear in Bandra, drinking iced oat matcha, looking for someone who doesn't ghost and actually has taste 👻",
    interests: ['thrift fashion', 'oat matcha', 'film 35mm', 'contemporary dance'],
    relationshipIntentions: 'Companionship & dating someone with creative drive',
    preferredAgeRange: [21, 26],
    preferredDistanceKm: 20,
    preferredGenerations: ['genz', 'zillenial'],
    completenessCategory: 'complete',
    completenessScore: 100,
    photos: [
      demoAsset('profile-906-primary.jpg'),
      demoAsset('profile-906-gallery-1.jpg'),
      demoAsset('profile-906-gallery-2.jpg'),
    ],
    initials: 'Z',
    isDemo: true,
    isVerified: true,
    status: 'online',
    lastSeen: 'Active now',
    isMatch: false,
    compatibilityScore: null,
  },

  // -------------------------------------------------------------
  // PROFILE 907: Rohan V. (Complete - 100%) - Discover Feed Candidate
  // -------------------------------------------------------------
  {
    id: 907,
    chatId: 907,
    name: 'Rohan V.',
    age: 27,
    gender: 'male',
    city: 'Bengaluru',
    era: 'zillenial',
    eraBadge: 'Zillenial 🎭',
    eraIcon: '🎭',
    ringColor: '#f59e0b',
    cornerEmoji: '🌊',
    vibeTag: 'Both worlds',
    profession: 'Distributed Systems Engineer',
    education: 'BITS Pilani',
    bio: "Grew up on MSN messenger and dial-up tones; now building high-throughput systems. Weekend bouldering at Equilibrium and searching for high-energy conversations 🌊",
    interests: ['rock bouldering', 'retro gaming', 'craft cider', 'scifi literature'],
    relationshipIntentions: 'Long-term partnership with curiosity and shared adventures',
    preferredAgeRange: [24, 30],
    preferredDistanceKm: 30,
    preferredGenerations: ['zillenial', 'millennial'],
    completenessCategory: 'complete',
    completenessScore: 100,
    photos: [
      demoAsset('profile-907-primary.jpg'),
      demoAsset('profile-907-gallery-1.jpg'),
      demoAsset('profile-907-gallery-2.jpg'),
    ],
    initials: 'R',
    isDemo: true,
    isVerified: true,
    status: 'online',
    lastSeen: 'Active now',
    isMatch: false,
    compatibilityScore: null,
  },

  // -------------------------------------------------------------
  // PROFILE 908: Ananya T. (Mostly Complete - 85%) - Discover Feed
  // Missing: relationshipIntentions (null)
  // -------------------------------------------------------------
  {
    id: 908,
    chatId: 908,
    name: 'Ananya T.',
    age: 28,
    gender: 'female',
    city: 'Delhi',
    era: 'millennial',
    eraBadge: 'Millennial ⚡',
    eraIcon: '⚡',
    ringColor: '#06b6d4',
    cornerEmoji: '🌸',
    vibeTag: 'Emotionally available',
    profession: 'Environmental Policy Analyst',
    education: 'JNU New Delhi',
    bio: "Passionate about climate policy and old Daryaganj book markets. Slow burn conversations, live Hindustani classical, and homemade dal makhani 🌸",
    interests: ['climate justice', 'urdu poetry', 'hiking in himachal', 'analog photography'],
    relationshipIntentions: null,
    preferredAgeRange: [27, 34],
    preferredDistanceKm: 40,
    preferredGenerations: ['millennial', 'zillenial'],
    completenessCategory: 'mostly_complete',
    completenessScore: 85,
    photos: [
      demoAsset('profile-908-primary.jpg'),
      demoAsset('profile-908-gallery-1.jpg'),
      demoAsset('profile-908-gallery-2.jpg'),
    ],
    initials: 'A',
    isDemo: true,
    isVerified: true,
    status: 'offline',
    lastSeen: 'last seen 4h ago',
    isMatch: false,
    compatibilityScore: null,
  },

  // -------------------------------------------------------------
  // PROFILE 909: Dev N. (Partially Complete - 60%) - Discover Feed
  // Missing: education, relationshipIntentions, preferredAgeRange (null)
  // -------------------------------------------------------------
  {
    id: 909,
    chatId: 909,
    name: 'Dev N.',
    age: 26,
    gender: 'male',
    city: 'Chennai',
    era: 'zillenial',
    eraBadge: 'Zillenial 🎭',
    eraIcon: '🎭',
    ringColor: '#f59e0b',
    cornerEmoji: '🎭',
    vibeTag: 'Hybrid feels',
    profession: 'Independent Documentary Filmmaker',
    education: null,
    bio: "Half workaholic on location, half couch potato listening to Carnatic fusion. Searching for genuine human depth without performative small talk 🎭",
    interests: ['cinematography', 'carnatic jazz', 'street food walks', 'vintage scooters'],
    relationshipIntentions: null,
    preferredAgeRange: null,
    preferredDistanceKm: 25,
    preferredGenerations: ['zillenial', 'genz'],
    completenessCategory: 'partially_complete',
    completenessScore: 60,
    photos: [
      demoAsset('profile-909-primary.jpg'),
      demoAsset('profile-909-gallery-1.jpg'),
      demoAsset('profile-909-gallery-2.jpg'),
    ],
    initials: 'D',
    isDemo: true,
    isVerified: true,
    status: 'offline',
    lastSeen: 'last seen 6h ago',
    isMatch: false,
    compatibilityScore: null,
  },

  // -------------------------------------------------------------
  // PROFILE 910: Meera S. (Partially Complete - 60%) - Discover Feed
  // Missing: education, preferredDistanceKm, preferredGenerations (null)
  // -------------------------------------------------------------
  {
    id: 910,
    chatId: 910,
    name: 'Meera S.',
    age: 24,
    gender: 'female',
    city: 'Mumbai',
    era: 'genz',
    eraBadge: 'Gen Z 💀',
    eraIcon: '💀',
    ringColor: '#a855f7',
    cornerEmoji: '🦋',
    vibeTag: 'Soft launch ready',
    profession: 'Art Director & Underground DJ',
    education: null,
    bio: "Curating gallery openings by daylight, spinning dark disco by midnight. Tell me your top 3 desert-island tracks and let's see if our energy aligns 🦋",
    interests: ['dark disco', 'contemporary art', 'analog synths', 'late night drives'],
    relationshipIntentions: 'Spontaneous creative connection that might turn into something real',
    preferredAgeRange: [22, 28],
    preferredDistanceKm: null,
    preferredGenerations: null,
    completenessCategory: 'partially_complete',
    completenessScore: 60,
    photos: [
      demoAsset('profile-910-primary.jpg'),
      demoAsset('profile-910-gallery-1.jpg'),
      demoAsset('profile-910-gallery-2.jpg'),
    ],
    initials: 'M',
    isDemo: true,
    isVerified: true,
    status: 'online',
    lastSeen: 'Active now',
    isMatch: false,
    compatibilityScore: null,
  },

  // -------------------------------------------------------------
  // PROFILE 911: Kavya R. (Complete - 100%) - Discover Feed
  // -------------------------------------------------------------
  {
    id: 911,
    chatId: 911,
    name: 'Kavya R.',
    age: 23,
    gender: 'female',
    city: 'Pune',
    era: 'genz',
    eraBadge: 'Gen Z 💀',
    eraIcon: '💀',
    ringColor: '#a855f7',
    cornerEmoji: '🎨',
    vibeTag: 'Cozy creative',
    profession: 'UI/UX Product Designer & Botanical Illustrator',
    education: 'Symbiosis Institute of Design',
    bio: "Obsessed with clean kerning, terrariums, and making cozy spaces. You'll find me sketching at Pagdandi or hunting for second-hand graphic novels 🌿",
    interests: ['botanical illustration', 'typography', 'board games', 'pour-over coffee'],
    relationshipIntentions: 'Long-term relationship built on mutual warmth and creativity',
    preferredAgeRange: [22, 27],
    preferredDistanceKm: 20,
    preferredGenerations: ['genz', 'zillenial'],
    completenessCategory: 'complete',
    completenessScore: 100,
    photos: [
      demoAsset('profile-911-primary.jpg'),
      demoAsset('profile-911-gallery-1.jpg'),
      demoAsset('profile-911-gallery-2.jpg'),
    ],
    initials: 'K',
    isDemo: true,
    isVerified: true,
    status: 'online',
    lastSeen: 'Active now',
    isMatch: false,
    compatibilityScore: null,
  },

  // -------------------------------------------------------------
  // PROFILE 912: Aditya M. (Mostly Complete - 85%) - Discover Feed
  // Missing: education (null)
  // -------------------------------------------------------------
  {
    id: 912,
    chatId: 912,
    name: 'Aditya M.',
    age: 25,
    gender: 'male',
    city: 'Jaipur',
    era: 'zillenial',
    eraBadge: 'Zillenial 🎭',
    eraIcon: '🎭',
    ringColor: '#f59e0b',
    cornerEmoji: '🪕',
    vibeTag: 'Old soul wanderer',
    profession: 'Boutique Heritage Restorer & Folk Musician',
    education: null,
    bio: "Restoring 200-year-old havelis and playing the kamayacha under desert stars. Looking for a road trip partner who loves old towns and spontaneous dhabas 🪕",
    interests: ['rajasthani folk', 'heritage architecture', 'motorcycling', 'desert camping'],
    relationshipIntentions: 'Companionship and seeing where mutual respect takes us',
    preferredAgeRange: [23, 29],
    preferredDistanceKm: 50,
    preferredGenerations: ['zillenial', 'genz'],
    completenessCategory: 'mostly_complete',
    completenessScore: 85,
    photos: [
      demoAsset('profile-912-primary.jpg'),
      demoAsset('profile-912-gallery-1.jpg'),
      demoAsset('profile-912-gallery-2.jpg'),
    ],
    initials: 'A',
    isDemo: true,
    isVerified: true,
    status: 'offline',
    lastSeen: 'last seen 3h ago',
    isMatch: false,
    compatibilityScore: null,
  },

  // -------------------------------------------------------------
  // PROFILE 913: Riya D. (Partially Complete - 55%) - Discover Feed
  // Missing: profession, education, preferredDistanceKm, relationshipIntentions (null)
  // -------------------------------------------------------------
  {
    id: 913,
    chatId: 913,
    name: 'Riya D.',
    age: 20,
    gender: 'female',
    city: 'Chandigarh',
    era: 'genz',
    eraBadge: 'Gen Z 💀',
    eraIcon: '💀',
    ringColor: '#a855f7',
    cornerEmoji: '⚡',
    vibeTag: 'Unapologetic energy',
    profession: null,
    education: null,
    bio: "Law student with too many opinions on courtroom dramas. Coffee over tea, sprint running in Sector 17, and always down for late-night ice cream runs 🍦",
    interests: ['constitutional law', 'badminton', 'true crime podcasts', 'gelato'],
    relationshipIntentions: null,
    preferredAgeRange: [20, 24],
    preferredDistanceKm: null,
    preferredGenerations: ['genz'],
    completenessCategory: 'partially_complete',
    completenessScore: 55,
    photos: [
      demoAsset('profile-913-primary.jpg'),
      demoAsset('profile-913-gallery-1.jpg'),
      demoAsset('profile-913-gallery-2.jpg'),
    ],
    initials: 'R',
    isDemo: true,
    isVerified: true,
    status: 'online',
    lastSeen: 'Active now',
    isMatch: false,
    compatibilityScore: null,
  },

  // -------------------------------------------------------------
  // PROFILE 914: Sneha P. (Mostly Complete - 85%) - Discover Feed
  // Missing: profession (null - literature student)
  // -------------------------------------------------------------
  {
    id: 914,
    chatId: 914,
    name: 'Sneha P.',
    age: 21,
    gender: 'female',
    city: 'Kolkata',
    era: 'genz',
    eraBadge: 'Gen Z 💀',
    eraIcon: '💀',
    ringColor: '#a855f7',
    cornerEmoji: '📚',
    vibeTag: 'Poetic nostalgia',
    profession: null,
    education: 'Presidency University Kolkata',
    bio: "Comparative literature major finding solace in College Street bookstores and tram rides. Tell me the poem that made you stop walking 📚",
    interests: ['bengali literature', 'tram routes', 'vintage fountain pens', 'street theatre'],
    relationshipIntentions: 'Slow, heartfelt romance that values vulnerability',
    preferredAgeRange: [20, 25],
    preferredDistanceKm: 25,
    preferredGenerations: ['genz', 'zillenial'],
    completenessCategory: 'mostly_complete',
    completenessScore: 85,
    photos: [
      demoAsset('profile-914-primary.jpg'),
      demoAsset('profile-914-gallery-1.jpg'),
      demoAsset('profile-914-gallery-2.jpg'),
    ],
    initials: 'S',
    isDemo: true,
    isVerified: true,
    status: 'offline',
    lastSeen: 'last seen 5h ago',
    isMatch: false,
    compatibilityScore: null,
  },

  // -------------------------------------------------------------
  // PROFILE 915: Kabir J. (Several Missing - 35%) - Discover Feed
  // Missing: bio, education, relationshipIntentions, preferences (all null)
  // -------------------------------------------------------------
  {
    id: 915,
    chatId: 915,
    name: 'Kabir J.',
    age: 27,
    gender: 'male',
    city: 'Goa',
    era: 'zillenial',
    eraBadge: 'Zillenial 🎭',
    eraIcon: '🎭',
    ringColor: '#f59e0b',
    cornerEmoji: '🎧',
    vibeTag: null,
    profession: 'Sound Engineer & Acoustic Consultant',
    education: null,
    bio: null,
    interests: ['sound design', 'ambient drones'],
    relationshipIntentions: null,
    preferredAgeRange: null,
    preferredDistanceKm: null,
    preferredGenerations: null,
    completenessCategory: 'several_missing',
    completenessScore: 35,
    photos: [
      demoAsset('profile-915-primary.jpg'),
      demoAsset('profile-915-gallery-1.jpg'),
      demoAsset('profile-915-gallery-2.jpg'),
    ],
    initials: 'K',
    isDemo: true,
    isVerified: true,
    status: 'offline',
    lastSeen: 'last seen 1d ago',
    isMatch: false,
    compatibilityScore: null,
  },

  // -------------------------------------------------------------
  // PROFILE 916: Vikram S. (Complete - 100%) - Discover Feed
  // -------------------------------------------------------------
  {
    id: 916,
    chatId: 916,
    name: 'Vikram S.',
    age: 29,
    gender: 'male',
    city: 'Delhi',
    era: 'millennial',
    eraBadge: 'Millennial ⚡',
    eraIcon: '⚡',
    ringColor: '#06b6d4',
    cornerEmoji: '🏔️',
    vibeTag: 'Peak ambition',
    profession: 'Principal Product Manager & Mountaineer',
    education: 'IIT Delhi',
    bio: "Building clean tech software from Monday to Friday, navigating Garhwal Himalayan passes on long weekends. Seeking an equal partner with passion, wit, and grit 🏔️",
    interests: ['alpine mountaineering', 'wilderness first aid', 'clean tech', 'jazz piano'],
    relationshipIntentions: 'Committed, serious relationship leading towards life partnership',
    preferredAgeRange: [26, 32],
    preferredDistanceKm: 50,
    preferredGenerations: ['millennial', 'zillenial'],
    completenessCategory: 'complete',
    completenessScore: 100,
    photos: [
      demoAsset('profile-916-primary.jpg'),
      demoAsset('profile-916-gallery-1.jpg'),
      demoAsset('profile-916-gallery-2.jpg'),
    ],
    initials: 'V',
    isDemo: true,
    isVerified: true,
    status: 'offline',
    lastSeen: 'last seen 7h ago',
    isMatch: false,
    compatibilityScore: null,
  },

  // -------------------------------------------------------------
  // PROFILE 917: Farhan K. (Partially Complete - 55%) - Discover Feed
  // Missing: vibeTag, education, relationshipIntentions, preferredGenerations (null)
  // -------------------------------------------------------------
  {
    id: 917,
    chatId: 917,
    name: 'Farhan K.',
    age: 28,
    gender: 'male',
    city: 'Hyderabad',
    era: 'millennial',
    eraBadge: 'Millennial ⚡',
    eraIcon: '⚡',
    ringColor: '#06b6d4',
    cornerEmoji: '♟️',
    vibeTag: null,
    profession: 'Quantitative Risk Analyst',
    education: null,
    bio: "Data by day, rapid chess blitz by night. If you can beat me in 10-minute chess or show me a hidden biryani gem in the old city, dinner is on me ♟️",
    interests: ['chess blitz', 'dum biryani', 'marathon training'],
    relationshipIntentions: null,
    preferredAgeRange: [25, 30],
    preferredDistanceKm: 30,
    preferredGenerations: null,
    completenessCategory: 'partially_complete',
    completenessScore: 55,
    photos: [
      demoAsset('profile-917-primary.jpg'),
      demoAsset('profile-917-gallery-1.jpg'),
      demoAsset('profile-917-gallery-2.jpg'),
    ],
    initials: 'F',
    isDemo: true,
    isVerified: true,
    status: 'offline',
    lastSeen: 'last seen 8h ago',
    isMatch: false,
    compatibilityScore: null,
  },

  // -------------------------------------------------------------
  // PROFILE 918: Tanisha B. (Mostly Complete - 85%) - Discover Feed
  // Missing: preferredAgeRange (null)
  // -------------------------------------------------------------
  {
    id: 918,
    chatId: 918,
    name: 'Tanisha B.',
    age: 26,
    gender: 'non-binary',
    city: 'Chennai',
    era: 'zillenial',
    eraBadge: 'Zillenial 🎭',
    eraIcon: '🎭',
    ringColor: '#f59e0b',
    cornerEmoji: '🪸',
    vibeTag: 'Oceanic calm',
    profession: 'Marine Biologist & Dive Instructor',
    education: 'Madras Christian College',
    bio: "Studying coral reef restoration in the Gulf of Mannar. Saltwater hair, warm coastal sunsets, and always curious about what lies beneath the surface 🪸",
    interests: ['scuba diving', 'coral ecology', 'underwater photography', 'surf culture'],
    relationshipIntentions: 'Looking for a kindred spirit who loves open water and genuine connection',
    preferredAgeRange: null,
    preferredDistanceKm: 40,
    preferredGenerations: ['zillenial', 'genz'],
    completenessCategory: 'mostly_complete',
    completenessScore: 85,
    photos: [
      demoAsset('profile-918-primary.jpg'),
      demoAsset('profile-918-gallery-1.jpg'),
      demoAsset('profile-918-gallery-2.jpg'),
    ],
    initials: 'T',
    isDemo: true,
    isVerified: true,
    status: 'online',
    lastSeen: 'Active now',
    isMatch: false,
    compatibilityScore: null,
  },

  // -------------------------------------------------------------
  // PROFILE 919: Dia S. (Several Missing - 30%) - Discover Feed
  // Missing: profession, education, vibeTag, relationshipIntentions, preferences (null)
  // -------------------------------------------------------------
  {
    id: 919,
    chatId: 919,
    name: 'Dia S.',
    age: 19,
    gender: 'female',
    city: 'Ahmedabad',
    era: 'genz',
    eraBadge: 'Gen Z 💀',
    eraIcon: '💀',
    ringColor: '#a855f7',
    cornerEmoji: '✨',
    vibeTag: null,
    profession: null,
    education: null,
    bio: "Here to see what Raahi is about.",
    interests: ['world cinema'],
    relationshipIntentions: null,
    preferredAgeRange: null,
    preferredDistanceKm: null,
    preferredGenerations: null,
    completenessCategory: 'several_missing',
    completenessScore: 30,
    photos: [
      demoAsset('profile-919-primary.jpg'),
      demoAsset('profile-919-gallery-1.jpg'),
      demoAsset('profile-919-gallery-2.jpg'),
    ],
    initials: 'D',
    isDemo: true,
    isVerified: true,
    status: 'offline',
    lastSeen: 'last seen 12h ago',
    isMatch: false,
    compatibilityScore: null,
  },

  // -------------------------------------------------------------
  // PROFILE 920: Siddharth R. (Several Missing - 25%) - Discover Feed
  // Missing: bio, education, interests (empty), vibeTag, intentions, preferences (null)
  // -------------------------------------------------------------
  {
    id: 920,
    chatId: 920,
    name: 'Siddharth R.',
    age: 30,
    gender: 'male',
    city: 'Kochi',
    era: 'millennial',
    eraBadge: 'Millennial ⚡',
    eraIcon: '⚡',
    ringColor: '#06b6d4',
    cornerEmoji: '⚓',
    vibeTag: null,
    profession: 'Naval Architect',
    education: null,
    bio: null,
    interests: [],
    relationshipIntentions: null,
    preferredAgeRange: null,
    preferredDistanceKm: null,
    preferredGenerations: null,
    completenessCategory: 'several_missing',
    completenessScore: 25,
    photos: [
      demoAsset('profile-920-primary.jpg'),
      demoAsset('profile-920-gallery-1.jpg'),
      demoAsset('profile-920-gallery-2.jpg'),
    ],
    initials: 'S',
    isDemo: true,
    isVerified: true,
    status: 'offline',
    lastSeen: 'last seen 2d ago',
    isMatch: false,
    compatibilityScore: null,
  },
]

// Reusable profile lookup utilities
export function getFictionalProfileById(id: number): FictionalDemoProfile | null {
  return TWENTY_DEMO_PROFILES.find(p => p.id === id) ?? null
}

export function getAllFictionalProfiles(): FictionalDemoProfile[] {
  return TWENTY_DEMO_PROFILES
}

export function getProfilesByCompleteness(category: CompletenessCategory): FictionalDemoProfile[] {
  return TWENTY_DEMO_PROFILES.filter(p => p.completenessCategory === category)
}
