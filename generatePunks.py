from PIL import Image
import hashlib, json, os, random
import probability as prob

# Keep track of punk metadata
allmetadata = []
# Keep track of punks created
punksCreated = 0
# Keep track of filehashes
fileHashes = []

os.makedirs("generated", exist_ok=True)

TOTAL_PUNKS = int(os.getenv("PUNK_COUNT", "10000"))
FILE_PREFIX = os.getenv("PUNK_PREFIX", "x402Punk")

# Punks
# Male = punks[0:4], Female = punks[4:8], Alien = punks[8], Ape = punks[9], Zombie = punks[10]
punks = ['punk01.png', 'punk02.png', 'punk03.png', 'punk04.png', 'punk05.png', 'punk06.png', 'punk07.png', 'punk08.png', 'punk09.png', 'punk10.png', 'punk11.png']
punkTypes = ['male', 'female', 'alien', 'ape', 'zombie']
backgrounds = ['bg01.png', 'bg02.png', 'bg03.png']
smokes = ['smoke01.png', 'smoke02.png', 'smoke03.png']


def event_occurs(probability):
	"""Return True with the given probability (0-1 range)."""
	return random.random() < probability


def weighted_choice(options, weights):
	"""Pick a single option using the provided weights."""
	return random.choices(options, weights=weights, k=1)[0]

def generatePunk(punkType):
	# Metadata dictionary to keep track of attributes
	metadata = {}
	# This can probably be shortened using dynamic variable names or similar
	if punkType == 'male':
		attrDict = prob.maleAttr
		punkStack = Image.open(f"punks/{random.choice(punks[0:4])}")
		metadata['Punk Type'] = 'Male'
	elif punkType == 'female':
		attrDict = prob.femaleAttr
		punkStack = Image.open(f"punks/{random.choice(punks[4:8])}")
		metadata['Punk Type'] = 'Female'
	elif punkType == 'alien':
		attrDict = prob.alienAttr
		punkStack = Image.open(f"punks/{punks[8]}")
		metadata['Punk Type'] = 'Alien'
	elif punkType == 'ape':
		attrDict = prob.apeAttr
		punkStack = Image.open(f"punks/{punks[9]}")
		metadata['Punk Type'] = 'Ape'
	elif punkType == 'zombie':
		attrDict = prob.zombieAttr
		punkStack = Image.open(f"punks/{punks[10]}")
		metadata['Punk Type'] = 'Zombie'

	attributeCount = 0
	basedir = f"attributes/{punkType}/"
	hasHeadAttr = event_occurs(0.7)
	if hasHeadAttr:
		headAttrs = [f"{basedir}head/{item[0]}" for item in attrDict['head'].items()]
		headChoice = Image.open(weighted_choice(headAttrs, list(attrDict['head'].values())))
		punkStack.paste(headChoice, (0, 0), headChoice)
		attributeCount += 1
		metadata['Head Attribute'] = str(headChoice.filename.split("/")[-1])
	if punkType == 'male' or punkType == 'zombie':
		hasFacialHair = event_occurs(0.3)
		if hasFacialHair:
			facialHairAttrs = [f"{basedir}facialhair/{item[0]}" for item in attrDict['facialhair'].items()]
			facialHairChoice = Image.open(weighted_choice(facialHairAttrs, list(attrDict['facialhair'].values())))
			punkStack.paste(facialHairChoice, (0, 0), facialHairChoice)
			attributeCount += 1
			metadata['Facial Hair'] = str(facialHairChoice.filename.split("/")[-1])
	hasGlasses = event_occurs(0.7)
	if hasGlasses:
		glassesAttrs = [f"{basedir}eyes/{item[0]}" for item in attrDict['eyes'].items()]
		if glassesAttrs:
			glassesChoice = Image.open(weighted_choice(glassesAttrs, list(attrDict['eyes'].values())))
			punkStack.paste(glassesChoice, (0, 0), glassesChoice)
			attributeCount += 1
			metadata['Glasses'] = str(glassesChoice.filename.split("/")[-1])
	hasMouthModifier = event_occurs(0.6)
	if hasMouthModifier:
		mouthAttrs = [f"{basedir}mouth/{item[0]}" for item in attrDict['mouth'].items()]
		if mouthAttrs:
			mouthChoice = Image.open(weighted_choice(mouthAttrs, list(attrDict['mouth'].values())))
			punkStack.paste(mouthChoice, (0, 0), mouthChoice)
			attributeCount += 1
			metadata['Mouth Modifier'] = str(mouthChoice.filename.split("/")[-1])
	hasMask = event_occurs(0.025)
	if not hasMask:
		hasSmoke = event_occurs(0.25)
		if hasSmoke:
			smokeChoice = Image.open(f"attributes/uni/smoke/{weighted_choice(smokes, [0.33, 0.33, 0.34])}")
			punkStack.paste(smokeChoice, (0, 0), smokeChoice)
			attributeCount += 1
			metadata['Smoking'] = str(smokeChoice.filename.split("/")[-1])
	if hasMask and punkType != 'ape':
		maskChoice = Image.open(f"{basedir}mask/mask01.png")
		punkStack.paste(maskChoice, (0, 0), maskChoice)
		attributeCount += 1
		metadata['Wearing Mask'] = str(maskChoice.filename.split("/")[-1])
	hasEarring = event_occurs(0.15)
	if hasEarring:
		earringChoice = Image.open(f"{basedir}earring/earring01.png")
		punkStack.paste(earringChoice, (0, 0), earringChoice)
		attributeCount += 1
		metadata['Earrings'] = str(earringChoice.filename.split("/")[-1])
	hasNecklace = event_occurs(0.2)
	if hasNecklace:
		neckAttrs = [f"{basedir}neck/{item[0]}" for item in attrDict['neck'].items()]
		if neckAttrs:
			neckChoice = Image.open(weighted_choice(neckAttrs, list(attrDict['neck'].values())))
			punkStack.paste(neckChoice, (0, 0), neckChoice)
			attributeCount += 1
			metadata['Neck Modifier'] = str(neckChoice.filename.split("/")[-1])
	metadata['Total Attributes'] = attributeCount
	print(f"Creating {punkType} with {attributeCount} attributes")
	allmetadata.append(metadata)
	return punkStack

# While loop for total number of punks to be generated
while punksCreated < TOTAL_PUNKS:

	# Select punk and start stacking randomly chosen layers using the appropriate function
	output = generatePunk(weighted_choice(punkTypes, [0.5, 0.3, 0.05, 0.06, 0.09]))

	fileHash = hashlib.md5(output.tobytes())
	hashDigest = fileHash.hexdigest()
	if hashDigest not in fileHashes:
		fileHashes.append(hashDigest)
		punkBg = Image.open(f"backgrounds/{weighted_choice(backgrounds, [0.7, 0.2, 0.1])}")
		punkBg.paste(output, (0, 0), output)
		output_path = f"generated/{FILE_PREFIX}_{punksCreated}.png"
		punkBg.save(output_path)
		print(f"Wrote file {os.path.basename(output_path)} ({hashDigest})")
		punksCreated += 1

with open(f"generated/metadata.json", "w") as outFile:
	json.dump(allmetadata, outFile) 
